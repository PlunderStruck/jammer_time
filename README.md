# Jammer Time

- **Main Functionality**:
  - The application allows users to load two CSV files: one containing machine data and another containing shift schedules.
  - It calculates and displays summarized information about the machine states during different shifts, considering breaks and errors. This includes aggregating error durations and annotating entries based on the shifts and breaks from the schedule.
- **Key Components**:
  - **Data Processing**: It parses the machine and shift schedule data from CSV files, enriching machine entries with shift and break annotations and handling errors and durations.
  - **Summarization Logic**: The program summarizes machine entries, considering consecutive errors and their durations, applying shift codes, and dividing time according to shift occurrences.
  - **UI Components**: Includes buttons for loading CSV files, a progress bar for tracking the calculation process, and a tree view to display results in a structured format.
- **Detailed Features**:
  - **Shift and Error Handling**: It evaluates whether machine downtimes categorized as 'ERROR' reach a cumulative duration that affects shift productivity, applying necessary annotations or exclusions based on predefined rules.
  - **Interactive GUI**: The application offers a graphical user interface with buttons to load files, initiate calculations, and a menu bar for additional functionalities like accessing documentation and application info.
  - **Results Display**: Summarized data is displayed in a tree view, where each node represents a shift code, and child nodes represent different machine states and their durations during those shifts.

## Installation Instructions

### **1. Clone the repository**

```sh
git clone https://github.com/PlunderStruck/jammer_time.git
cd jammer_time
```

### **2. Set up a virtual environment (not necessary but recommended)**

```sh
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### **3. Install dependencies**

```sh
pip install -r requirements.txt
```

### **4. Run the script**

```sh
python Machine_State_Calculator-1.1.py
```
