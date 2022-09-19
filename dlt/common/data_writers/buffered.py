from typing import List, IO, Any

from dlt.common.utils import uniq_id
from dlt.common.typing import TDataItem
from dlt.common.sources import TDirectDataItem
from dlt.common.data_writers import TLoaderFileFormat
from dlt.common.data_writers.exceptions import InvalidFileNameTemplateException
from dlt.common.data_writers.writers import DataWriter
from dlt.common.schema.typing import TTableSchemaColumns


class BufferedDataWriter:
    def __init__(self, file_format: TLoaderFileFormat, file_name_template: str, buffer_max_items: int = 5000, file_max_bytes: int = None):
        self.file_format = file_format
        self._file_format_spec = DataWriter.data_format_from_file_format(self.file_format)
        # validate if template has correct placeholders
        self.file_name_template = file_name_template
        self.all_files: List[str] = []
        self.buffer_max_items = buffer_max_items
        self.file_max_bytes = file_max_bytes

        self._current_columns: TTableSchemaColumns = None
        self._file_name: str = None
        self._buffered_items: List[TDataItem] = []
        self._writer: DataWriter = None
        self._file: IO[Any] = None
        try:
            self._rotate_file()
        except TypeError:
            raise InvalidFileNameTemplateException(file_name_template)

    def write_data_item(self, item: TDirectDataItem, columns: TTableSchemaColumns) -> None:
        # rotate file if columns changed and writer does not allow for that
        # as the only allowed change is to add new column (no updates/deletes), we detect the change by comparing lengths
        if self._writer and not self._writer.data_format().supports_schema_changes and len(columns) != len(self._current_columns):
            self._rotate_file()
        # until the first chunk is written we can change the columns schema freely
        self._current_columns = columns
        if isinstance(item, List):
            # items coming in single list will be written together, not matter how many are there
            self._buffered_items.extend(item)
        else:
            self._buffered_items.append(item)
        # flush if max buffer exceeded
        if len(self._buffered_items) > self.buffer_max_items:
            self._flush_items()
        # rotate the file if max_bytes exceeded
        if self.file_max_bytes and self._file and self._file.tell() > self.file_max_bytes:
            self._rotate_file()

    def _rotate_file(self) -> None:
        self.close_writer()
        self._file_name = self.file_name_template % uniq_id() + "." + self._file_format_spec.file_extension

    def _flush_items(self) -> None:
        if len(self._buffered_items) > 0:
            # we only open a writer when there are any files in the buffer and first flush is requested
            if not self._writer:
                # create new writer and write header
                if self._file_format_spec.is_binary_format:
                    self._file = open(self._file_name, "wb")
                else:
                    self._file = open(self._file_name, "wt", encoding="utf-8")
                self._writer = DataWriter.from_file_format(self.file_format, self._file)
                self._writer.write_header(self._current_columns)
            # write buffer
            self._writer.write_data(self._buffered_items)
            self._buffered_items.clear()

    def close_writer(self) -> None:
        # if any buffered items exist, flush them
        self._flush_items()
        # if writer exists then close it
        if self._writer:
            # write the footer of a file
            self._writer.write_footer()
            # add file written to the list so we can commit all the files later
            self.all_files.append(self._file_name)
            self._file.close()
            self._writer = None
            self._file = None