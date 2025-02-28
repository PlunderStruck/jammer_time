import sys
import os
from markdown import markdown
import pandas as pd
from datetime import time
from collections import defaultdict
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton, QTreeView, QActionGroup, 
                             QFileDialog, QHBoxLayout, QLabel, QTextEdit, QHeaderView, QProgressBar, QAction, QMessageBox, QMainWindow, QTextBrowser)
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QFont, QColor, QIcon, QPixmap
from PyQt5.QtCore import Qt, QSize, QCoreApplication

def summarize_machine_entries_with_exclusion(updated_data):
    """
    Goes through machine entries (already annotated with shift codes, breaks, etc.)
    and:
    1) Sums durations for each machine state per shift code (result).
    2) Tracks jam counts in two ways:
       - jam_count_by_shift[shift_code][machine] = number of jam events for that shift
       - overall_jam_count[machine] = total jam events across all shifts

    A "jam" = a valid consecutive ERROR block under 1 hour,
    not interrupted by breaks/shift crossovers.
    """
    from collections import defaultdict

    # Durations for each shift_code -> machine -> state
    result = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))

    # Jam counts:
    jam_count_by_shift = defaultdict(lambda: defaultdict(int))
    overall_jam_count = defaultdict(int)

    skip_consecutive_errors = defaultdict(bool)
    error_entries_buffer = defaultdict(list)
    error_duration_buffer = defaultdict(float)

    for machine, entries in updated_data.items():
        for entry in entries:
            timestamp, state, weekday, duration, *codes = entry
            shift_codes = [c for c in codes if c.startswith("SC:")]
            is_break = ('break' in codes)
            is_shiftcrossover = ('shiftcrossover' in codes)

            # 1) If break or shift crossover, reset current error buffer
            if is_break or is_shiftcrossover:
                error_entries_buffer[machine].clear()
                error_duration_buffer[machine] = 0.0
                skip_consecutive_errors[machine] = True
                continue

            # 2) If skipping errors (set true after a break/crossover), ignore ERROR
            if state == "ERROR" and skip_consecutive_errors[machine]:
                continue

            # 3) If we see an ERROR, accumulate in the buffer
            if state == "ERROR":
                error_entries_buffer[machine].append((timestamp, state, weekday, duration, shift_codes))
                error_duration_buffer[machine] += duration
                continue

            # 4) We hit a NON-ERROR; check the buffer
            if error_duration_buffer[machine] >= 3600:
                # Discard buffer if total errors >= 1 hour
                error_entries_buffer[machine].clear()
                error_duration_buffer[machine] = 0.0
            else:
                # If we actually have an error buffer, it's a valid jam event
                if error_entries_buffer[machine]:
                    # Gather all shift codes in the buffer
                    shifts_in_block = set()
                    for buf_ts, buf_state, buf_wd, buf_dur, buf_codes in error_entries_buffer[machine]:
                        for sc in buf_codes:
                            if sc.startswith("SC:"):
                                shifts_in_block.add(sc)

                    # Increment jam counts for each shift code involved
                    for sc in shifts_in_block:
                        jam_count_by_shift[sc][machine] += 1

                    # Also increment the overall machine jam count
                    overall_jam_count[machine] += 1

                # Flush these ERROR durations to the final result
                while error_entries_buffer[machine]:
                    buf_ts, buf_state, buf_wd, buf_dur, buf_codes = error_entries_buffer[machine].pop(0)
                    # Each error's duration is split across its shift codes
                    if buf_codes:
                        split_duration = buf_dur / len(buf_codes)
                        for sc in buf_codes:
                            if sc.startswith("SC:"):
                                result[sc][machine][buf_state] += split_duration

            # 5) Reset
            error_duration_buffer[machine] = 0.0
            skip_consecutive_errors[machine] = False

            # 6) Handle non-ERROR states
            if shift_codes and state != "ERROR":
                split_duration = duration / len(shift_codes)
                for sc in shift_codes:
                    result[sc][machine][state] += split_duration

    return result, jam_count_by_shift, overall_jam_count


def parse_time(entry):
    """
    Parses a time entry in the format 'Day Hour:Minute' into a tuple of (day, time).

    Parameters:
    - entry (str): The time entry to parse.

    Returns:
    - tuple: A tuple containing the day and time parsed from the entry.
    """
    # Check if the entry is NaN or 'n/a', and return None for both day and time if true
    if pd.isna(entry) or entry.strip().lower() == "n/a":
        return (None, None)
    
    # Split the entry into day and time components
    day, t = entry.split()
    
    # Split the time component into hour and minute components and convert them to integers
    hour, minute = map(int, t.split(':'))
    
    # Return a tuple containing the day and a time object constructed from the hour and minute
    return (day, time(hour, minute))

def process_shift_schedule_combined_dict(file_path):
    """ Process a CSV file of shift data into a structured dictionary format. """
    shift_data = pd.read_csv(file_path)
    
    schedule_dict = {}
    
    for _, row in shift_data.iterrows():
        shift_code = row['Shift Code']
        shift_start = row['Shift Start Time']
        shift_end = row['Shift End Time']
        
        # Parse times for the shift start and end
        start_day, start_time = parse_time(shift_start)
        end_day, end_time = parse_time(shift_end)
        
        # Key for breaks
        break_key = f"{shift_code} breaks"
        
        # Store the shift times as a tuple in the list under the shift code
        if shift_code not in schedule_dict:
            schedule_dict[shift_code] = []
        schedule_dict[shift_code].append((start_day, start_time, end_day, end_time))
        
        # Initialize breaks list if not present
        if break_key not in schedule_dict:
            schedule_dict[break_key] = []
        
        # Processing breaks - assuming break times are in pairs in columns labeled 'Break 1 Start', 'Break 1 End', etc.
        break_columns = [col for col in shift_data.columns if 'Break' in col or 'Lunch' in col]
        for i in range(0, len(break_columns), 2):  # Iterate in steps of 2 to get start and end together
            if i + 1 < len(break_columns):  # Check if there is a pair
                break_start = row[break_columns[i]]
                break_end = row[break_columns[i + 1]]
                
                if pd.notna(break_start) and pd.notna(break_end):
                    break_start_day, break_start_time = parse_time(break_start)
                    break_end_day, break_end_time = parse_time(break_end)
                    
                    # Append the break times as a tuple
                    schedule_dict[break_key].append(
                        (break_start_day, break_start_time, break_end_day, break_end_time)
                    )
    
    return schedule_dict

def parse_machine_data(file_path):
    # Read data from CSV file into a pandas DataFrame
    data = pd.read_csv(file_path)
    
    # Convert the 'Time' column to datetime format
    data['Time'] = pd.to_datetime(data['Time'])
    
    # Extract the weekday from the 'Time' column and add it as a new column named 'Weekday'
    data['Weekday'] = data['Time'].dt.day_name()
    
    # Determine the first and last datetime for the dataset
    datetime_range = (data['Time'].min(), data['Time'].max())
    
    # Create an empty dictionary to store machine data
    machine_data = {}
    
    # Iterate through each column (machine) in the DataFrame
    for machine in sorted(data.columns):
        # Exclude columns named 'Time' and 'Weekday'
        if machine != 'Time' and machine != 'Weekday':
            # Select rows with non-null values in columns 'Time', 'Weekday', and the current machine column
            valid_data = data[['Time', 'Weekday', machine]].dropna()
            
            # Create a new column 'Next_Time' which contains the next timestamp for each row
            valid_data['Next_Time'] = valid_data['Time'].shift(-1)
            
            # Calculate the duration between consecutive timestamps in seconds and store it in a new column 'Duration'
            valid_data['Duration'] = (valid_data['Next_Time'] - valid_data['Time']).dt.total_seconds()
            
            # Replace missing durations (NaN) with a default duration of 180 seconds
            valid_data.loc[valid_data['Duration'].isna(), 'Duration'] = 180
            
            # Combine the 'Time', machine readings, weekday, and duration into tuples and store them as entries for the current machine
            machine_entries = list(zip(valid_data['Time'], valid_data[machine], valid_data['Weekday'], valid_data['Duration']))
            
            # Store the machine entries in the machine_data dictionary with the machine name as the key
            machine_data[machine] = machine_entries

    # Return the dictionary containing parsed machine data
    return machine_data, datetime_range
       
def within_time_period(start_day, start_time, end_day, end_time, current_day, current_time):
    # Dictionary mapping weekday names to their corresponding indices (0 for Monday, 1 for Tuesday, etc.)
    weekdays = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}
    
    # Get the index of the start day, end day, and current day from the weekdays dictionary
    start_index = weekdays[start_day]
    end_index = weekdays[end_day]
    current_index = weekdays[current_day]
    
    # Adjust the end index if it's before the start index to account for the next week
    if end_index < start_index:
        end_index += 7
        
    # Adjust the current index if it's before the start index to account for the next week
    if current_index < start_index:
        current_index += 7
        
    # Check if the current day falls within the specified period
    is_within_day = start_index <= current_index <= end_index
    
    # If the current day is within the specified period
    if is_within_day:
        # If the start, current, and end days are the same
        if start_index == current_index == end_index:
            # Check if the current time is within the specified time range
            return start_time <= current_time <= end_time
        # If the current day is the start day
        elif start_index == current_index:
            # Check if the current time is after the start time
            return current_time >= start_time
        # If the current day is the end day
        elif end_index == current_index:
            # Check if the current time is before the end time
            return current_time <= end_time
        # If the current day is between the start and end days
        else:
            # Return True since any time during these days is within the specified period
            return True
    
    # If the current day is not within the specified period
    return False

def update_machine_data(machine_data, schedule_dict):
    """
    Updates machine data with shift and break annotations, prepends 'SC:' to shift codes,
    and appends 'shiftcrossover' to entries without shifts or breaks.
    """
    updated_data = {}  # Initialize an empty dictionary to store updated machine data
    for machine_id, entries in machine_data.items():
        updated_entries = []  # Initialize an empty list to store updated entries for the current machine
        for entry in entries:
            entry_dt, status, weekday, duration = entry
            entry_dt = pd.to_datetime(entry_dt)  # Ensure the entry datetime is a pandas datetime object
            
            shifts_applied = []  # Initialize an empty list to store applied shifts
            is_break_applied = False  # Initialize a flag to track if a break is applied
            
            # Check each shift and break in the schedule dictionary
            for shift, times in schedule_dict.items():
                for time_range in times:
                    start_day, start_time, end_day, end_time = time_range
                    # Check if the entry falls within the time range of the shift or break
                    if within_time_period(start_day, start_time, end_day, end_time, weekday, entry_dt.time()):
                        if 'breaks' in shift:
                            # If a break is applied, add it to the list of applied shifts and set the flag
                            if not is_break_applied:
                                shifts_applied.append("break")
                                is_break_applied = True
                        else:
                            # If a shift is applied, prepend 'SC:' to the shift code and add it to the list of applied shifts
                            shifts_applied.append(f"SC:{shift}")

            # Determine the annotation for the entry based on applied shifts and breaks
            if shifts_applied:
                # If any shifts or breaks are applied, extend the original tuple with them
                updated_entry = entry + tuple(shifts_applied)
            else:
                # If no shifts or breaks are applied, append 'shiftcrossover' to the original tuple
                updated_entry = entry + ("shiftcrossover",)

            # Add the updated entry to the list of updated entries for the current machine
            updated_entries.append(updated_entry)

        # Add the list of updated entries for the current machine to the updated_data dictionary
        updated_data[machine_id] = updated_entries

    # Return the dictionary containing updated machine data
    return updated_data

class CSVSummarizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.main_widget = QWidget(self)
        self.setCentralWidget(self.main_widget)
        self.setupUI()

    def setupUI(self):
        self.configureWindow()
        self.createMenuBar()
        self.createWidgets()
        self.setupLayouts()

    def configureWindow(self):
        self.setWindowTitle('JammerTime')
        
        screen = QApplication.primaryScreen().geometry()
        screenWidth = screen.width()
        screenHeight = screen.height()

        # Calculate window size and position as a fraction of screen size
        windowWidth = int(screenWidth * 0.35)
        windowHeight = int(screenHeight * 0.6)
        windowX = int((screenWidth - windowWidth) / 2)  # Center the window
        windowY = int((screenHeight - windowHeight) / 2)  # Center the window

        self.setGeometry(windowX, windowY, windowWidth, windowHeight)
        self.setMinimumSize(int(windowWidth * 1), int(windowHeight * 1))  # Minimum size as 80% of the current size, converted to integer

        self.setWindowIcon(QIcon(self.resourcePath('jam.png')))
        self.applyStyling()

    def createMenuBar(self):
        menuBar = self.menuBar()
        fileMenu = menuBar.addMenu('&File')
        helpMenu = menuBar.addMenu('&Help')

        exitAction = QAction('&Exit', self)
        exitAction.setShortcut('Ctrl+Q')
        exitAction.triggered.connect(self.close)
        fileMenu.addAction(exitAction)

        # Add actions to the help menu
        aboutAction = QAction('&About', self)
        aboutAction.triggered.connect(self.aboutDialog)
        helpMenu.addAction(aboutAction)
        
        docAction = QAction('&Documentation', self)
        docAction.triggered.connect(self.showDocumentation)
        helpMenu.addAction(docAction)

    def showDocumentation(self):
        # Pass the icon path to the MarkdownViewer
        icon_path = self.resourcePath('blackhole.png')  # Make sure this is the correct path to your icon
        self.docViewer = MarkdownViewer(icon_path)
        self.docViewer.show()

    def aboutDialog(self):
        # Create a QMessageBox
        msgBox = QMessageBox()
        msgBox.setWindowTitle("About")
        msgBox.setText("<font color='#8e8e8e'>v4<br>AbyssWarden <br>Made by aydsaloi</font>")
        msgBox.setWindowIcon(QIcon(self.resourcePath('blackhole.png')))  
        # Load and resize the logo
        logo = QPixmap(self.resourcePath('blackhole.png'))  # Load your logo
        resizedLogo = logo.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # Resize logo to 64x64 pixels
        
        # Set the resized logo as the icon pixmap
        msgBox.setIconPixmap(resizedLogo)
        
        # Apply custom styling
        msgBox.setStyleSheet("""
            QMessageBox {
                background-color: #2a2a2a;
                color: #8e8e8e;
                font-family: 'Cascadia Code';
                font-size: 10pt;
            }
            QPushButton {
                background-color: #1f1f1f;
                color: #8e8e8e;
                border: 1px solid #1f1f1f;
                border-radius: 7px;
                padding: 5px;
                font-weight: bold;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #313232;
                border-color: #313232;
            }
            QPushButton:pressed {
                background-color: #313232;
                border-color: #313232;
            }
        """)

        # Show the message box
        msgBox.exec_()


    def createWidgets(self):
        self.createButtons()
        self.createInfoText()
        self.createProgressBar()
        self.createDateRangeLabel()
        self.createTreeView()

    def setupLayouts(self):
        self.layout = QVBoxLayout()  # Define the main vertical layout
        self.button_layout = QHBoxLayout()  # Horizontal layout for buttons
        
        # Add widgets to the button layout
        self.button_layout.addWidget(self.load_schedule_btn)
        self.button_layout.addWidget(self.load_machine_btn)
        self.button_layout.addWidget(self.calculate_btn)
        
        # Add layouts and widgets to the main layout
        self.layout.addLayout(self.button_layout)
        self.layout.addWidget(self.info_text)
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(self.date_range_label)
        self.layout.addWidget(self.tree_view)
        
        # Set the main layout to the central widget
        self.main_widget.setLayout(self.layout)

    def createButtons(self):
        self.load_schedule_btn = self.createButton('Schedules CSV', 'calendar.png', 22)
        self.load_machine_btn = self.createButton('Machine CSV', 'floppy.png', 24)
        self.calculate_btn = self.createButton('Calculate', 'calculator.png', 24)
        
        self.load_schedule_btn.clicked.connect(self.load_schedule_csv)
        self.load_machine_btn.clicked.connect(self.load_machine_csv)
        self.calculate_btn.clicked.connect(self.calculate)

    def createButton(self, text, icon_file, icon_size):
        button = QPushButton(text)
        button.setIcon(QIcon(self.resourcePath(icon_file)))
        button.setIconSize(QSize(icon_size, icon_size))
        button.setStyleSheet(self.buttonStyle())
        return button

    def createInfoText(self):
        self.info_text = QTextEdit()
        self.info_text.setFont(QFont("Consolas", 9))
        self.info_text.setReadOnly(True)
        self.info_text.setMaximumHeight(60)
        self.info_text.setStyleSheet(self.infoTextStyle())
        self.info_text.append("")

    def createDateRangeLabel(self):
        self.date_range_label = QLabel('')
        self.date_range_label.setStyleSheet("color: #8e8e8e;")
        self.date_range_label.setFont(QFont("Consolas", 9))

    def createTreeView(self):
        self.tree_view = QTreeView()
        self.model = QStandardItemModel()
        self.tree_view.setModel(self.model)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.header().setStretchLastSection(False)
        self.tree_view.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tree_view.setStyleSheet(self.treeViewStyle())

    def resourcePath(self, relative_path):
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, 'assets', relative_path)
    
    def buttonStyle(self):
        return """
            QPushButton {
                background-color: #1f1f1f;
                color: #8e8e8e;
                border: 1px solid #1f1f1f;
                border-radius: 7px;
                padding: 5px;
                font-weight: bold;
                font-size: 10pt;
                font-family: 'Cascadia Code';
            }
            QPushButton:hover {
                background-color: #313232;
                border-color: #313232;
            }
            QPushButton:pressed {
                background-color: #313232;
                border-color: #313232;
            }
            """

    def infoTextStyle(self):
        return """
            QTextEdit {
                background-color: #2a2a2a;  /* Dark grey background */
                border: 2px solid #2a2a2a;  /* Styled border matching the overall dark theme */
                border-radius: 1px;
                color: #8e8e8e;  /* Light grey text for better visibility */
            }
            QScrollBar:vertical {
                border: none;
                background: #2a2a2a;  /* Scrollbar background matching the QTextEdit */
                width: 10px;
                margin: 10px 0 10px 0;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;  /* Slightly lighter grey than the scrollbar for visibility */
                min-height: 20px;
            }
            QScrollBar::add-line:vertical {
                background: #2a2a2a;  /* Same as scrollbar background */
                height: 10px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
            }
            QScrollBar::sub-line:vertical {
                background: #2a2a2a;  /* Same as scrollbar background */
                height: 10px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                background: #1f1f1f;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """

    def treeViewStyle(self):
        return """
            QTreeView {
                background-color: #2a2a2a;  /* Dark grey background */
                border: 2px solid #2a2a2a;  /* Slightly lighter grey border */
                border-radius: 1px;
                color: #8e8e8e;  /* Light grey text */
            }
            QScrollBar:vertical {
                border: none;
                background: #2a2a2a;  /* Match the tree view background */
                width: 10px;
                margin: 10px 0 10px 0;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;  /* Slightly lighter grey than the scrollbar background */
                min-height: 20px;
            }
            QScrollBar::add-line:vertical {
                background: #2a2a2a;  /* Same as scrollbar background */
                height: 10px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
            }
            QScrollBar::sub-line:vertical {
                background: #2a2a2a;  /* Same as scrollbar background */
                height: 10px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                background: #1f1f1f;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """
    
    def applyStyling(self):
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(self.backgroundRole(), QColor(31, 31, 31))
        self.setPalette(p)
        
        # Styling for the menu bar
        style = """
            QMenuBar {
                background-color: #1f1f1f;
                color: #8e8e8e;
                border: 1px solid #1f1f1f;
                font-weight: bold;
                font-size: 8pt;
                font-family: 'Cascadia Code';
            }
            QMenuBar::item {
                padding: 5px 10px;
                border-radius: 7px;
            }
            QMenuBar::item:selected {
                background-color: #313232;
            }
            QMenuBar::item:pressed {
                background-color: #313232;
                border-color: #313232;
            }
            QMenu {
                background-color: #1f1f1f;
                color: #8e8e8e;
                border: 1px solid #1f1f1f;
                font-family: 'Cascadia Code';
                font-size: 8pt;
            }
            QMenu::item {
                padding: 5px 15px;
                border-radius: 7px;
            }
            QMenu::item:selected {
                background-color: #313232;
            }
            """

        self.menuBar().setStyleSheet(style)
        
    def createProgressBar(self):
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)  # Initially hide the progress bar
        self.styleProgressBar()  # Apply the custom styling
        
    def styleProgressBar(self):
        style = """
            QProgressBar {
                border: 2px solid #2a2a2a;
                border-radius: 5px;
                background-color: #1f1f1f;
                text-align: center; /* Center the text (if you decide to show any) */
                color: #8e8e8e; /* Color of the text */
                font-family: 'Cascadia Code'
            }
            QProgressBar::chunk {
                background-color: #313232;
                width: 20px;
                margin: 0.5px;
                border-radius: 2px;
            }
            """
        self.progress_bar.setStyleSheet(style) 
        
    def load_schedule_csv(self):
        self.schedule_csv, _ = QFileDialog.getOpenFileName(self, "Open Schedule CSV", "", "CSV files (*.csv)")
        if self.schedule_csv:
            self.info_text.append(f"Loaded schedule CSV: {self.schedule_csv}")

    def load_machine_csv(self):
        self.machine_csv, _ = QFileDialog.getOpenFileName(self, "Open Machine CSV", "", "CSV files (*.csv)")
        if self.machine_csv:
            self.info_text.append(f"Loaded machine CSV: {self.machine_csv}")

    def calculate(self):
        if not hasattr(self, 'schedule_csv') or not self.schedule_csv \
        or not hasattr(self, 'machine_csv') or not self.machine_csv:
            self.info_text.append("Please load both schedule and machine CSV files before calculating.")
            self.progress_bar.setValue(0)
            return

        self.progress_bar.setVisible(True)
        
        try:
            self.progress_bar.setValue(10)
            QCoreApplication.processEvents()  # Keep UI responsive

            machine_data, datetime_range = parse_machine_data(self.machine_csv)
            self.progress_bar.setValue(30)
            QCoreApplication.processEvents()

            schedule_data = process_shift_schedule_combined_dict(self.schedule_csv)
            self.progress_bar.setValue(50)
            QCoreApplication.processEvents()

            updated_machine_data = update_machine_data(machine_data, schedule_data)
            self.progress_bar.setValue(70)
            QCoreApplication.processEvents()

            # We now get 3 results back
            summarized_data, jam_count_by_shift, overall_jam_count = summarize_machine_entries_with_exclusion(updated_machine_data)
            self.progress_bar.setValue(90)
            QCoreApplication.processEvents()

            # Optional: Log overall jam counts to info_text
            self.info_text.append("Overall Machine Jams (all shifts):")
            for machine_id, count in overall_jam_count.items():
                self.info_text.append(f" - {machine_id}: {count} jam(s) total")

            # Now display results in the tree view
            self.display_results(summarized_data, datetime_range, jam_count_by_shift, overall_jam_count)

            self.progress_bar.setValue(100)
            QCoreApplication.processEvents()

        except Exception as e:
            self.info_text.append("Error during calculation: " + str(e))
            self.progress_bar.setValue(0)
        finally:
            self.progress_bar.setVisible(False)

    def display_results(self, data, datetime_range, jam_count_by_shift, overall_jam_count):
        """
        data                = summarized_data (shift_code -> machine -> state -> duration in SECONDS)
        jam_count_by_shift  = jam_count_by_shift[shift_code][machine] -> # of jam events in that shift
        overall_jam_count   = overall_jam_count[machine] -> total jam events across all shifts

        This displays two sections:
        1. "Overall Machine Jams": each machine's jam count & % share,
            plus a final row showing "Total Jams" across all lines.
        2. Per-shift breakdown: machine jam count, avg jam time in MINUTES, states/durations in HOURS.
        """
        start_date, end_date = datetime_range
        self.date_range_label.setText(f'DateTime Range: {start_date} | {end_date}')
        self.model.clear()

        # We'll use two columns: "Item" and "Detail"
        self.model.setHorizontalHeaderLabels(['Item', 'Detail'])

        # Font definitions
        shift_font = QFont("Consolas", 13, QFont.Bold)
        machine_font = QFont("Consolas", 12)
        state_font = QFont("Cascadia Code", 11)

        # Colors
        color_error_text = QColor(193, 131, 85)
        color_available_text = QColor(79, 163, 85)
        color_full_text = QColor(97, 170, 230)

        #
        # SECTION 1: Overall Machine Jams
        #
        overall_root_item = QStandardItem("Overall Machine Jams")
        overall_root_item.setFont(shift_font)
        overall_root_item.setFlags(overall_root_item.flags() & ~Qt.ItemIsEditable)

        overall_root_detail = QStandardItem("")
        overall_root_detail.setFlags(overall_root_detail.flags() & ~Qt.ItemIsEditable)

        # 1) Calculate the grand total of all jams (across all machines)
        grand_total_jams = sum(overall_jam_count.values())

        # 2) For each machine, show total jam count and % of total
        for machine_id in sorted(overall_jam_count.keys()):
            machine_jams = overall_jam_count[machine_id]
            if grand_total_jams > 0:
                jam_pct = (machine_jams / grand_total_jams) * 100.0
            else:
                jam_pct = 0.0

            # e.g. "Machine_01: 5 jam(s) (33.33%)"
            machine_item_text = f"{machine_id}: {machine_jams} jam(s) ({jam_pct:.2f}%)"
            machine_item = QStandardItem(machine_item_text)
            machine_item.setFont(machine_font)
            machine_item.setFlags(machine_item.flags() & ~Qt.ItemIsEditable)

            detail_item = QStandardItem("")
            detail_item.setFlags(detail_item.flags() & ~Qt.ItemIsEditable)

            overall_root_item.appendRow([machine_item, detail_item])

        # 3) Add a final line at the bottom for total jams across all lines
        total_line_text = f"Total Jams: {grand_total_jams}"
        total_line_item = QStandardItem(total_line_text)
        total_line_item.setFont(machine_font)
        total_line_item.setFlags(total_line_item.flags() & ~Qt.ItemIsEditable)

        total_line_detail = QStandardItem("")
        total_line_detail.setFlags(total_line_detail.flags() & ~Qt.ItemIsEditable)

        # Append that row so it appears last in the overall section
        overall_root_item.appendRow([total_line_item, total_line_detail])

        # Attach the overall root item to the model
        self.model.appendRow([overall_root_item, overall_root_detail])

        #
        # SECTION 2: Break down by SHIFT CODE
        #
        for shift_code in sorted(data.keys()):
            shift_display_text = shift_code[len("SC:"):]  # e.g. "Shift A"
            shift_item = QStandardItem(shift_display_text)
            shift_item.setFont(shift_font)
            shift_item.setFlags(shift_item.flags() & ~Qt.ItemIsEditable)

            shift_detail_item = QStandardItem("")
            shift_detail_item.setFlags(shift_detail_item.flags() & ~Qt.ItemIsEditable)

            # For each machine in this shift
            for machine_id in sorted(data[shift_code].keys()):
                shift_jams = jam_count_by_shift[shift_code].get(machine_id, 0)
                total_error_seconds = data[shift_code][machine_id].get("ERROR", 0.0)

                # Compute average jam time in minutes
                if shift_jams > 0:
                    avg_jam_time_minutes = (total_error_seconds / shift_jams) / 60.0
                else:
                    avg_jam_time_minutes = 0.0

                # e.g. "Machine_01 (2 jams, avg jam 15.00 mins)"
                machine_item_text = (
                    f"{machine_id} ({shift_jams} jams, avg jam {avg_jam_time_minutes:.2f} mins)"
                )
                machine_item = QStandardItem(machine_item_text)
                machine_item.setFont(machine_font)
                machine_item.setFlags(machine_item.flags() & ~Qt.ItemIsEditable)

                machine_detail_item = QStandardItem("")
                machine_detail_item.setFlags(machine_detail_item.flags() & ~Qt.ItemIsEditable)

                # For each state/duration in this shift->machine
                for state, duration_in_seconds in sorted(data[shift_code][machine_id].items()):
                    # Convert each state duration to hours for display
                    hours = duration_in_seconds / 3600.0
                    duration_text = f"{hours:.2f} hrs"

                    state_item = QStandardItem(f"{state}: {duration_text}")
                    state_item.setFont(state_font)
                    state_item.setFlags(state_item.flags() & ~Qt.ItemIsEditable)

                    # colorize based on state
                    if "ERROR" in state:
                        state_item.setForeground(color_error_text)
                    elif "AVAILABLE" in state:
                        state_item.setForeground(color_available_text)
                    elif "FULL" in state:
                        state_item.setForeground(color_full_text)

                    state_detail_item = QStandardItem("")
                    state_detail_item.setFlags(state_detail_item.flags() & ~Qt.ItemIsEditable)
                    machine_item.appendRow([state_item, state_detail_item])

                shift_item.appendRow([machine_item, machine_detail_item])

            self.model.appendRow([shift_item, shift_detail_item])

        self.tree_view.expandAll()


    def resize_tree_view_columns(self, index):
        self.tree_view.header().setSectionResizeMode(QHeaderView.ResizeToContents)

class MarkdownViewer(QMainWindow):
    def __init__(self, icon_path):
        super().__init__()
        self.setWindowIcon(QIcon(icon_path))
        self.initUI()

    def initUI(self):
        # Text browser widget with specific dark theme
        self.textBrowser = QTextBrowser(self)
        self.textBrowser.setStyleSheet(self.infoTextStyle())
        self.setCentralWidget(self.textBrowser)
        self.setGeometry(100, 100, 600, 500)
        self.setWindowTitle('Documentation')
        self.loadInitialFile()
        self.show()

    def loadInitialFile(self):
        base_path = os.path.dirname(__file__)
        file_path = os.path.join(base_path, 'assets', 'Documentation.txt')
        try:
            with open(file_path, 'r') as file:
                markdown_content = file.read()
            html_content = markdown(markdown_content)
            self.textBrowser.setHtml(html_content)
        except Exception as e:
            self.textBrowser.setHtml(f"<h1>File could not be loaded</h1><p>Error: {str(e)}</p>")

    def infoTextStyle(self):
        return """
            QTextBrowser {
                background-color: #2a2a2a;
                border: 2px solid #2a2a2a;
                border-radius: 0px;
                color: #ffffff;
                font-family: 'Helvetica';
                font-size: 12pt;
            }
            QScrollBar:vertical {
                border: none;
                background: #2a2a2a;
                width: 10px;
                margin: 10px 0 10px 0;
            }
            QScrollBar::handle:vertical {
                background: #3d3d3d;
                min-height: 20px;
            }
            QScrollBar::add-line:vertical {
                background: #2a2a2a;
                height: 10px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
            }
            QScrollBar::sub-line:vertical {
                background: #2a2a2a;
                height: 10px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                background: #1f1f1f;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = CSVSummarizerApp()
    ex.show()
    sys.exit(app.exec_())
