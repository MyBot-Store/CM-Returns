# CM-Returns
CM Bot Performance for WIX Deployment 
Trading Performance Dashboard
A self-updating equity curve dashboard that pulls live data from IBKR,
displays it on GitHub Pages, and embeds into your Wix website.
Architecture
```
IBKR Flex Query API
      ↓
performance_sync.py  (runs weekly via GitHub Actions)
      ↓
data/performance_data.json  (committed to this repo)
      ↓
index.html + Chart.js  (served via GitHub Pages)
      ↓
Wix iframe embed  (your public performance page)
```
---
SETUP GUIDE (Follow in order — do not skip steps)
PHASE 1 — GitHub Repository
Go to https://github.com and sign in (create free account if needed)
Click the "+" icon → "New repository"
Name it: `trading-performance` (or any name you prefer)
Set visibility to: Public (required for GitHub Pages)
Click "Create repository"
Upload all files from this folder into the repo root:
performance_sync.py
index.html
data/performance_data.json
.github/workflows/sync.yml
Make sure the folder structure in GitHub looks like:
```
   trading-performance/
   ├── index.html
   ├── performance_sync.py
   ├── data/
   │   └── performance_data.json
   └── .github/
       └── workflows/
           └── sync.yml
   ```
---
PHASE 2 — Enable GitHub Pages
In your GitHub repo, click "Settings" tab
In the left sidebar, click "Pages"
Under "Source", select: Deploy from a branch
Branch: main / Folder: / (root)
Click Save
Wait 1-2 minutes, then your dashboard will be live at:
`https://YOUR_GITHUB_USERNAME.github.io/trading-performance/`
Visit that URL to confirm you see the loading screen
---
PHASE 3 — Update index.html with Your Repo URL
Open index.html in the GitHub editor (click the file → pencil icon)
Find this line near the top of the <script> section:
```
   const DATA_URL = "https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME/main/data/performance_data.json";
   ```
Replace YOUR_GITHUB_USERNAME and YOUR_REPO_NAME with your actual values
Example: `https://raw.githubusercontent.com/johntan/trading-performance/main/data/performance_data.json`
Click "Commit changes"
---
PHASE 4 — Add GitHub Secrets (IBKR Credentials)
These are stored securely in GitHub — never visible in your code.
In your GitHub repo, click "Settings" tab
In the left sidebar, click "Secrets and variables" → "Actions"
Click "New repository secret" and add each of these three secrets:
Secret 1:
Name:  IBKR_FLEX_TOKEN
Value: (paste your IBKR Flex Web Service token)
Secret 2:
Name:  IBKR_QUERY_ID
Value: (paste your Activity Flex Query ID)
Secret 3:
Name:  STARTING_BALANCE
Value: (your account starting balance, e.g. 10000.00)
Where to find your Token and Query ID:
→ Log into IBKR Client Portal
→ Performance & Reports → Flex Queries
→ Gear icon next to "Flex Web Service Configuration" → copy Token
→ Pencil icon next to your TradesViz flex query → copy Query ID
---
PHASE 5 — Run First Sync Manually
In your GitHub repo, click the "Actions" tab
Click "Weekly Performance Sync" in the left list
Click "Run workflow" → "Run workflow" (green button)
Watch the workflow run — it takes about 30-60 seconds
When complete (green tick), click the run to see logs
Go back to your repo — you should see data/performance_data.json
has been updated with real trade data
Visit your GitHub Pages URL — the charts should now appear
---
PHASE 6 — Embed into Wix
Copy your GitHub Pages URL:
`https://YOUR_GITHUB_USERNAME.github.io/trading-performance/`
Open your Wix Editor
Click "+" (Add elements) → Embed → "Embed a Widget" → "HTML iframe"
Click the iframe element → "Enter Code"
Paste this code (replace the URL with yours):
```html
   <iframe
     src="https://YOUR_GITHUB_USERNAME.github.io/trading-performance/"
     width="100%"
     height="820"
     frameborder="0"
     scrolling="yes"
     style="border:none; border-radius:10px;">
   </iframe>
   ```
Click Apply → Preview → check it looks correct
Switch to Mobile View in Wix Editor and adjust height to 650px for mobile
Publish your Wix site
---
PHASE 7 — Ongoing (Automatic)
After setup, everything runs itself:
Every Monday at 9am SGT, GitHub Actions pulls fresh data from IBKR
data/performance_data.json is updated automatically
Your Wix page reflects the latest data the next time a visitor loads it
No manual action required from you
If you ever need to update manually (e.g. after a big week), go to:
GitHub → Actions → Weekly Performance Sync → Run workflow
---
Troubleshooting
Dashboard shows "Could not load performance data"
→ Check that DATA_URL in index.html has your correct username and repo name
→ Make sure your repo is Public (not Private)
→ Wait 2-3 minutes after first enabling GitHub Pages
GitHub Actions fails with "ERROR"
→ Click the failed run → expand the "Run performance sync" step
→ Check your IBKR_FLEX_TOKEN and IBKR_QUERY_ID secrets are correct
→ Make sure your IBKR Flex Token has not expired (set to 1 year)
Equity curve shows $0 or flat
→ Check STARTING_BALANCE secret is set correctly (e.g. "10000.00")
→ Confirm your Flex Query includes "Trades" section with "Executions" selected
→ Confirm date range in Flex Query is "Last 365 Days" not a fixed past date
Charts appear but data seems wrong
→ IBKR commission values are already negative in Flex data — this is handled
→ Check if your Flex Query is set to one account only (not multiple accounts)
