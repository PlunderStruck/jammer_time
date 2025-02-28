# Jammer Time

I ultimately wrote this program to precisely measure the monetary cost of package sortation machine jams at my workplace. For some reason, there was no existing program that did this. Believe it or not, I was so motivated by spite from the incessant jams that I learned to code just to make this program a reality.  

This script is **PID (Parcel Identification Machine) and sortation machine agnostic**, at least at the largest logistics company in the world (you can Google it). It automatically detects how many machine lines are in the data and identifies the machine codes present.  

### **Challenges in Coding the Script**  

One of the biggest challenges was that the machines at my workplace report both jams and downtime using the same code: **ERROR**. This meant I couldn't simply calculate the duration between timestamps, append those durations to each respective row, and filter out and sum whatever machine codes I wanted. Instead, I had to design the script to account for only the **ERROR** codes that occurred during operational time windows.  

To achieve this, I had to append each row of machine data with a code that refers to the **shift during which it was recorded**. However, that wasn’t enough. The PID goes to sleep before the shift starts and during breaks. It only resumes operation when someone manually restarts it. If the machine isn't restarted **exactly** at the beginning of the shift or immediately after breaks, the total jam time would be **inflated**.  

Since it’s impossible to start the machine **on the dot** (mainly due to twice-daily full-shift meetings), the script had to account for non-jam **ERROR** codes that occur during operational periods. To do this, I programmed it to **ignore consecutive ERROR codes** that appear immediately after a break, lunch, or shift start.  

### **Accounting for Other Anomalies**  

In some cases, the PID falls asleep **before a break or the end of a shift** due to a lack of work-in-progress (WIP) or low staffing, which happens a lot after the holiday season. The script also **excludes consecutive ERROR codes** from jam totals if they are interrupted by the start of a break period or the end of a shift.  

Another issue was building closures for maintenance and holidays. My solution to this may be a bit of a hack, but I’ll let you judge. Since I’ve **never seen a jam last longer than an hour** (or even 20 minutes), the script assumes that any **long ERROR streak** during an operational period—**not immediately following a shift start or break**—is probably due to **maintenance or a closure**. Therefore, it **excludes ERROR streaks** that match those conditions.  

### **Improving Performance with Vectorization**  

Another major challenge was making the script **efficient**. Initially, I used **`iterrows()`** to loop through each row of data when merging machine data with the schedule data and when checking which shift a row belonged to. **This was SLOW AS HELL.**  

Since I needed the script to process **years of data efficiently**, I had to find a better solution. Eventually, I discovered **vectorization** and implemented it where needed. Now, the script can process **a full year's worth of data in about one minute**.  

I have no real standard to compare my code against, so while I assume it has its fair share of errors, I don’t know what they are—aside from **maybe** some unused variables and the fact that the entire script is in **one giant file**.  

### **How to Use the Program**  

To see how the program works, simply start it, select the sample machine and schedule data from the folder, and press **Calculate**.  

---

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
