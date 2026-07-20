"""
Project Tree Exporter - A PyQt5 application for visualizing and exporting project file structures.

This application provides a collapsible tree view of your project files, allowing you to:
- Browse project directories with a collapsible tree structure
- Select/deselect files using checkboxes
- Copy the file tree structure to clipboard
- Export selected file contents to a text file

Installation
------------
Create a conda environment with Python 3.11 and PyQt5:

    conda create -n export_project python=3.11 pyqt=5 -y
    conda activate export_project

Then run the script:

    python export_project.py

Usage
-----
1. Click "Select on Computer" to choose your project folder
2. Use "Update" to refresh the tree view
3. Collapse/expand folders by clicking the arrow icons
4. Check/uncheck files to select them
5. Use the action buttons to copy or export selected files
"""

import os
import sys
import tempfile
from typing import Any, NoReturn

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QColor, QPainter, QPixmap, QPolygon
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: Directory names to skip entirely while scanning the project folder.
IGNORED_DIRS = ".git", ".vscode", ".github", "__pycache__", ".idea"

#: File extensions (lowercase, with leading dot) to skip while scanning.
IGNORED_EXTS = {".pyc"}


class ProjectTreeExporter(QMainWindow):
    """
    Main window class for the Project Tree Exporter application.

    Provides a GUI for browsing project files in a tree structure with
    collapsible folders and file selection checkboxes.

    Attributes
    ----------
    project_folder : str
        The currently loaded project directory path.
    tree_widget : QTreeWidget
        The main tree widget displaying the file structure.
    folder_field : QLineEdit
        Input field for the project folder path.
    export_path_field : QLineEdit
        Input field for the export file path.
    """

    def __init__(self) -> None:
        """
        Initialize the main window and build the UI.
        """
        super().__init__()
        self.project_folder = ""
        self.setWindowTitle("Project Tree Exporter")
        self.resize(700, 600)
        self._build_ui()

    def _build_ui(self) -> None:
        """
        Build the user interface components and layout.

        Creates all widgets, sets up layouts, and connects signals to slots.
        """
        right_arrow, down_arrow = self._make_arrow_files()

        # Apply dark theme (black background, white text).
        self.setStyleSheet(
            "QWidget { background-color: #000000; color: #FFFFFF; }"
            "QLineEdit { background-color: #1e1e1e; color: #FFFFFF;"
            " border: 1px solid #444444; }"
            "QPushButton { background-color: #2d2d2d; color: #FFFFFF;"
            " border: 1px solid #555555; padding: 4px; }"
            "QPushButton:hover { background-color: #3d3d3d; }"
            "QTreeWidget { background-color: #1e1e1e; color: #FFFFFF;"
            " border: 1px solid #444444; }"
            "QTreeWidget::item { color: #FFFFFF; }"
            "QTreeWidget::item:hover { background-color: #3d3d3d;"
            " color: #FFFFFF; }"
            "QTreeWidget::item:selected { background-color: #094771;"
            " color: #FFFFFF; }"
            "QHeaderView::section { background-color: #2d2d2d;"
            " color: #FFFFFF; border: 1px solid #444444; }"
            f"QTreeView::branch:has-children:closed {{"
            f" image: url({right_arrow}); }}"
            f"QTreeView::branch:has-children:open {{"
            f" image: url({down_arrow}); }}"
        )

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Row 1: Folder selection
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Project Folder:"))
        self.folder_field = QLineEdit()
        folder_row.addWidget(self.folder_field)
        main_layout.addLayout(folder_row)

        # Row 2: Select / Update / Copy tree buttons.
        button_row = QHBoxLayout()
        select_btn = QPushButton("Select on Computer")
        select_btn.clicked.connect(self.select_folder)
        update_btn = QPushButton("Update")
        update_btn.clicked.connect(self.update_tree)
        copy_tree_btn = QPushButton("Copy tree to clipboard")
        copy_tree_btn.clicked.connect(self.copy_tree_to_clipboard)
        button_row.addWidget(select_btn)
        button_row.addWidget(update_btn)
        button_row.addWidget(copy_tree_btn)
        main_layout.addLayout(button_row)

        # Row 3: Tree view with checkboxes.
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Name"])
        self.tree_widget.setHeaderHidden(True)
        main_layout.addWidget(self.tree_widget)

        # Row 4: Action buttons.
        action_row = QHBoxLayout()
        collapse_btn = QPushButton("Collapse all")
        collapse_btn.clicked.connect(self.tree_widget.collapseAll)
        unselect_btn = QPushButton("Unselect all files")
        unselect_btn.clicked.connect(lambda: self._set_all_checks(False))
        select_all_btn = QPushButton("Select all files")
        select_all_btn.clicked.connect(lambda: self._set_all_checks(True))
        copy_res_btn = QPushButton("Copy result to clipboard")
        copy_res_btn.clicked.connect(self.copy_result_to_clipboard)
        export_btn = QPushButton("Export result as TXT")
        export_btn.clicked.connect(self.export_result_as_txt)
        for btn in (
            collapse_btn,
            unselect_btn,
            select_all_btn,
            copy_res_btn,
            export_btn,
        ):
            action_row.addWidget(btn)
        main_layout.addLayout(action_row)

        # Row 5: Export path field.
        export_row = QHBoxLayout()
        export_row.addWidget(QLabel("Export TXT path:"))
        self.export_path_field = QLineEdit(self._default_export_path())
        export_row.addWidget(self.export_path_field)
        main_layout.addLayout(export_row)

    @staticmethod
    def _make_arrow_files() -> tuple[str, str]:
        """
        Create temporary arrow icon files for tree view branch indicators.

        Returns
        -------
        tuple[str, str]
            Paths to the right arrow (collapsed) and down arrow (expanded) PNG files.
        """
        tmp = tempfile.gettempdir()
        right_path = os.path.join(tmp, "pte_arrow_right.png")
        down_path = os.path.join(tmp, "pte_arrow_down.png")

        def draw(points: list[tuple[int, int]], out_path: str) -> None:
            """
            Draw a polygon and save as PNG.

            Parameters
            ----------
            points : list[tuple[int, int]]
                List of (x, y) coordinates for the polygon vertices.
            out_path : str
                Output file path for the PNG image.
            """
            pix = QPixmap(12, 12)
            pix.fill(Qt.transparent)
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(QPolygon([QPoint(*p) for p in points]))
            painter.end()
            pix.save(out_path, "PNG")

        # Right-pointing (collapsed) and down-pointing (expanded) triangles.
        draw([(3, 2), (3, 10), (9, 6)], right_path)
        draw([(2, 3), (10, 3), (6, 9)], down_path)
        return right_path.replace(os.sep, "/"), down_path.replace(os.sep, "/")

    @staticmethod
    def _default_export_path() -> str:
        """
        Get the default export file path.

        Returns
        -------
        str
            Default path in the user's Downloads folder.
        """
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        return os.path.join(downloads, "exported_files.txt")

    @staticmethod
    def _is_file_item(item: QTreeWidgetItem) -> bool:
        """
        Check if a tree widget item represents a file.

        Parameters
        ----------
        item : QTreeWidgetItem
            The tree widget item to check.

        Returns
        -------
        bool
            True if the item is a file, False if it's a directory.
        """
        return item.data(0, Qt.UserRole + 1) == "file"

    def select_folder(self) -> None:
        """
        Open a file dialog to select a project folder.

        Updates the folder field and refreshes the tree view if a folder is selected.
        """
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if folder:
            self.folder_field.setText(folder)
            self.update_tree()

    def update_tree(self) -> None:
        """
        Update the tree view with the current folder's contents.

        Clears the existing tree and populates it with the directory structure
        from the folder specified in the folder field.
        """
        folder = self.folder_field.text().strip()
        if not folder or not os.path.isdir(folder):
            return
        self.project_folder = folder
        self.tree_widget.clear()

        root_item = QTreeWidgetItem([os.path.basename(folder.rstrip(os.sep))])
        root_item.setData(0, Qt.UserRole, folder)
        root_item.setData(0, Qt.UserRole + 1, "dir")
        self.tree_widget.addTopLevelItem(root_item)
        self._populate(root_item, folder)
        self.tree_widget.collapseAll()

    def _populate(self, parent_item: QTreeWidgetItem, path: str) -> None:
        """
        Recursively populate a tree widget item with directory contents.

        Parameters
        ----------
        parent_item : QTreeWidgetItem
            The parent tree item to populate with children.
        path : str
            The filesystem path corresponding to the parent item.
        """
        try:
            entries = sorted(os.listdir(path))
        except OSError:
            return

        dirs = [e for e in entries if os.path.isdir(os.path.join(path, e)) and e not in IGNORED_DIRS]
        files = [
            e
            for e in entries
            if os.path.isfile(os.path.join(path, e)) and os.path.splitext(e)[1].lower() not in IGNORED_EXTS
        ]

        for d in dirs:
            child = QTreeWidgetItem([d])
            full = os.path.join(path, d)
            child.setData(0, Qt.UserRole, full)
            child.setData(0, Qt.UserRole + 1, "dir")
            parent_item.addChild(child)
            self._populate(child, full)

        for f in files:
            child = QTreeWidgetItem([f])
            full = os.path.join(path, f)
            child.setData(0, Qt.UserRole, full)
            child.setData(0, Qt.UserRole + 1, "file")
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(0, Qt.Unchecked)
            parent_item.addChild(child)

    def _set_all_checks(self, checked: bool) -> None:
        """
        Set the check state for all file items in the tree.

        Parameters
        ----------
        checked : bool
            If True, check all files. If False, uncheck all files.
        """
        state = Qt.Checked if checked else Qt.Unchecked

        def recurse(item: QTreeWidgetItem) -> None:
            """
            Recursively set check state for file items.

            Parameters
            ----------
            item : QTreeWidgetItem
                The current tree item to process.
            """
            if self._is_file_item(item):
                item.setCheckState(0, state)
            for i in range(item.childCount()):
                recurse(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            recurse(self.tree_widget.topLevelItem(i))

    def _build_tree_text(self) -> str:
        """
        Build a text representation of the tree structure.

        Returns
        -------
        str
            A string with the tree structure using +--- and \\--- connectors.
            Returns empty string if the tree has no items.
        """
        if self.tree_widget.topLevelItemCount() == 0:
            return ""
        root = self.tree_widget.topLevelItem(0)
        lines = [root.text(0)]

        def recurse(item: QTreeWidgetItem, prefix: str) -> None:
            """
            Recursively build tree text for an item and its children.

            Parameters
            ----------
            item : QTreeWidgetItem
                The current tree item to process.
            prefix : str
                The prefix string for the current indentation level.
            """
            count = item.childCount()
            for idx in range(count):
                child = item.child(idx)
                last = idx == count - 1
                connector = "\\--- " if last else "+--- "
                extension = "    " if last else "|   "
                lines.append(f"{prefix}{connector}{child.text(0)}")
                recurse(child, prefix + extension)

        recurse(root, "")
        return "\n".join(lines)

    def copy_tree_to_clipboard(self) -> None:
        """
        Copy the tree structure text to the clipboard.

        Copies the text representation of the entire tree to the system clipboard.
        """
        text = self._build_tree_text()
        if text:
            QApplication.clipboard().setText(text)

    def _collect_selected_files(self) -> list[Any]:
        """
        Collect paths of all selected (checked) files.

        Returns
        -------
        list[Any]
            List of absolute file paths for all checked file items.
        """
        selected = []

        def recurse(item: QTreeWidgetItem) -> None:
            """
            Recursively collect selected files from an item and its children.

            Parameters
            ----------
            item : QTreeWidgetItem
                The current tree item to process.
            """
            if self._is_file_item(item) and item.checkState(0) == Qt.Checked:
                selected.append(item.data(0, Qt.UserRole))
            for i in range(item.childCount()):
                recurse(item.child(i))

        for i in range(self.tree_widget.topLevelItemCount()):
            recurse(self.tree_widget.topLevelItem(i))
        return selected

    def _build_result_text(self) -> str:
        """
        Build text containing contents of all selected files.

        Returns
        -------
        str
            A string with each selected file's relative path as a header
            followed by its contents, separated by blank lines.
        """
        parent = os.path.dirname(self.project_folder.rstrip(os.sep))
        blocks = []
        for path in self._collect_selected_files():
            rel = os.path.relpath(path, parent)
            rel = rel.replace(os.sep, "/")
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except OSError as exc:
                content = f"[Could not read file: {exc}]"
            blocks.append(f" ===== {rel} ===== \n\n{content}")
        return "\n\n".join(blocks)

    def copy_result_to_clipboard(self) -> None:
        """
        Copy the contents of selected files to the clipboard.

        Copies the text built by _build_result_text() to the system clipboard.
        """
        text = self._build_result_text()
        if text:
            QApplication.clipboard().setText(text)

    def export_result_as_txt(self) -> None:
        """
        Export the contents of selected files to a text file.

        Writes the text built by _build_result_text() to the path specified
        in the export path field. Creates parent directories if needed.
        """
        text = self._build_result_text()
        path = self.export_path_field.text().strip()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            pass


def main() -> NoReturn:
    """
    Main entry point for the application.

    Creates the QApplication instance, initializes the main window,
    and starts the event loop.
    """
    app = QApplication(sys.argv)
    window = ProjectTreeExporter()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
