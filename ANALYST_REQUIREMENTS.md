# Analyst Requirements Checklist

This document tracks all information needed from analysts to configure the financial news agent.

---

## 1. Research Portal Access

### Investment Bank Portals
- [ ] **JP Morgan**
  - [ ] Exact portal name/URL (e.g., Morgan Markets, J.P. Morgan Research Portal)
  - [ ] Login credentials (username/password)
  - [ ] Two-factor authentication method (if applicable)
  - [ ] Typical report format (PDF, HTML, both?)
  - [ ] How to identify "new" reports (date filter, RSS feed, etc.)

- [ ] **Other Investment Banks**
  - [ ] List all other banks they access
  - [ ] Portal URLs and login credentials for each
  - [ ] Report access methods

### Substack Subscriptions
# working on Joey forwarding from his inbox to my email
- [ ] **List of Substack authors to monitor**
  - [ ] Author name and Substack URL for each
  - [ ] Which ones have email/RSS feeds enabled
  - [ ] Which ones require web scraping
  - [ ] Login credentials for paid subscriptions

### Other Content Sources (Future)
- [X] YouTube channels to monitor
- [ ] Twitter/X accounts to follow
- [X] Podcast feeds

---

## 2. Coverage & Themes Configuration

### Stock Coverage
- [X] **List of tickers currently covered**
  - [X] Primary tickers (high priority)
  - [X] Secondary tickers (monitor but lower priority)
  - [ ] Any ticker aliases or related symbols (e.g., ADRs, different exchanges)

### Investment Theses/Themes
- [ ] **List of themes to track**
  - [ ] Theme name
  - [ ] Description/keywords for each theme
  - [ ] Priority level (high/medium/low)

  Example format:
  ```
  Theme: "AI Infrastructure Buildout"
  Keywords: data center, GPU, inference, training, compute capacity
  Priority: High
  ```

- [ ] **How often do themes change?**
  - [ ] Weekly? Monthly? Ad-hoc?
  - [ ] Who updates themes?

---

## 3. Filing & Organization System

### Current Workflow
- [ ] **How do analysts currently organize research?**
  - [ ] Folder structure (by ticker? by date? by source?)
  - [ ] File naming conventions
  - [ ] Tagging system (if any)
  - [ ] Storage location (local folders, cloud, shared drive?)

### Integration Requirements
- [ ] **Where should processed reports be saved?**
  - [ ] Local file path
  - [ ] Cloud storage (Dropbox, Google Drive, OneDrive?)
  - [ ] Database/CRM system?

- [ ] **Tagging/metadata requirements**
  - [ ] Auto-tag by ticker?
  - [ ] Auto-tag by theme?
  - [ ] Auto-tag by source (bank name, author)?
  - [ ] Date-based organization?

- [ ] **File naming format preference**
  - Example: `YYYYMMDD_TICKER_SOURCE_TITLE.pdf`
  - Or: `JPM_NVDA_Q4_Earnings_Preview_20260121.pdf`

---

## 4. Email Digest Configuration

### Email Setup
- [ ] **Sender email configuration**
  - [ ] Gmail account to send from (or other SMTP provider)
  - [ ] App-specific password (for Gmail)
  - [ ] SMTP server details (if not Gmail)

### Recipients
- [ ] **Who receives the daily digest?**
  - [ ] Primary analyst email(s)
  - [ ] CC any team members?
  - [ ] Different emails for different tickers/themes?

### Digest Format Preferences
- [ ] **Preferred email format**
  - [ ] HTML formatted email
  - [ ] Plain text
  - [ ] PDF attachment

- [ ] **Content organization**
  - [ ] Group by ticker?
  - [ ] Group by source?
  - [ ] Group by theme?
  - [ ] Show all sources, or only "relevant" findings?

- [ ] **Preferred sending time**
  - [ ] Morning (before market open)?
  - [ ] Evening (after market close)?
  - [ ] Specific time (e.g., 7:00 AM EST)?

---

## 5. Authentication & Security

### Credential Storage
- [ ] **How to securely provide credentials?**
  - [ ] Direct input into .env file (local only)?
  - [ ] Password manager integration?
  - [ ] Separate encrypted file?

### Session Management
- [ ] **Cookie extraction method**
  - [ ] Manual export from browser?
  - [ ] Automated login via Selenium/Playwright?
  - [ ] How often do sessions expire?

### Two-Factor Authentication
- [ ] **Which portals use 2FA?**
  - [ ] SMS codes
  - [ ] Authenticator apps
  - [ ] Email verification
  - [ ] How to handle programmatically?

---

## 6. Monitoring & Scheduling

### Frequency
- [ ] **Daily digest schedule**
  - [ ] Run once daily? Multiple times?
  - [ ] Weekdays only, or include weekends?
  - [ ] Skip market holidays?

### Alerting
- [ ] **Immediate alerts for high-priority content?**
  - [ ] Separate email for urgent items?
  - [ ] SMS/Slack notifications?
  - [ ] What constitutes "urgent"?

### Backup & Logging
- [ ] **Where to store logs?**
  - [ ] Error logs when scraping fails
  - [ ] Activity logs (what was processed)
  - [ ] Who monitors logs?

---

## 7. Content Filtering & Relevance

### Relevance Criteria
- [X] **What makes content "relevant"?**
  - [X] Mentions ticker explicitly?
  - [X] Mentions theme keywords?
  - [X] Macro coverage explicitly connected to TMT sector from Reuters and CNBC
  - [ ] From specific analysts/authors?
  - [ ] Minimum content length?

### False Positive Handling
- [ ] **How to handle borderline content?**
  - [ ] Include with "low confidence" flag?
  - [ ] Exclude entirely?
  - [ ] Separate section in digest?

---

## 8. Technical Environment

### Deployment
- [X] **Where will this run?**
  - [ ] Analyst's local machine (laptop/desktop)?
  - [X] Shared server?
  - [ ] Cloud VM?
  - [ ] Does machine stay on 24/7?

### Access & Updates
- [ ] **Who maintains the tool?**
  - [ ] IT team?
  - [ ] Analyst self-service?
  - [ ] How to add new sources/tickers?

### Backup Plan
- [ ] **What happens if tool fails?**
  - [ ] Email notification of failures?
  - [ ] Fallback to manual process?
  - [ ] How quickly must issues be resolved?

---

## 9. Testing & Validation

### Initial Testing
- [ ] **Test data for validation**
  - [ ] Sample reports to process
  - [ ] Known "good" examples for each source
  - [ ] Expected output format

### Feedback Loop
- [ ] **How to provide feedback on relevance?**
  - [ ] Mark items as "useful" or "not useful"?
  - [ ] Adjust filtering rules based on feedback?
  - [ ] Regular review cadence?

---

## 10. Future Enhancements (Nice-to-Have)

- [ ] **Additional features requested**
  - [ ] Comparison across analysts (e.g., consensus vs. outlier views)
  - [ ] Price target tracking
  - [ ] Sentiment analysis
  - [ ] Historical archive search
  - [ ] Mobile app access
  - [ ] Integration with trading platforms

---

## Notes & Follow-up Items

(Use this section for any additional context, special requirements, or open questions)

---

**Last Updated:** 2026-01-21
**Status:** Requirements gathering phase
