# OCI Appointment Checker — CLAUDE.md

## What This Repo Does

Automated slot checker and auto-booker for OCI (Overseas Citizen of India) appointments at the Indian Embassy Berlin (`appointment.indianembassyberlin.gov.in`).

- Runs every 2 minutes via cron-job.org → GitHub Actions `workflow_dispatch`
- Scans the appointment calendar for available slots
- Auto-books the earliest slot if it falls within 30 days of today
- Sends push notifications via ntfy.sh for all findings

## File Map

| File | Purpose |
|------|---------|
| `oci_checker.py` | Main script — checker + auto-booker |
| `test_booking_flow.py` | Local visual test (opens visible browser, pauses 40s before submit) |
| `run_test.sh` | Loads `.env.local` and runs `test_booking_flow.py` |
| `.env.local` | Local secrets (gitignored) |
| `.github/workflows/oci-checker.yml` | GitHub Actions workflow |
| `requirements.txt` | `selenium`, `webdriver-manager`, `Pillow` |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | No slots found |
| `1` | Slots found (may or may not have booked) |
| `2` | Script error |

## Site Flow (3 pages)

1. **Page 1** (`/`) — agree checkbox + PROCEED
2. **Page 2** (`/applicationscountry`) — select Jurisdiction=Berlin + agree + PROCEED
3. **Page 3** (`/application`) — select OCI → Fresh OCI → open datepicker → scan months

## Auto-Booking Logic

- Slot **within 30 days** (`AUTO_BOOK_DAYS`) → attempt auto-book
- Slot **beyond 30 days** → send ntfy notification only, keep monitoring
- `CANCEL_COUNT >= 2` → never auto-book (passport gets blocked for 2 weeks after 2 cancellations)
- Booking outcome `slot_gone` → slot was taken between detection and click, keep monitoring
- Booking outcome `already_booked` → user has an active appointment, must cancel manually first

## Key Selectors

```python
AGREE_CHECKBOX   = (By.ID, "agree")
PROCEED_BUTTON   = (By.ID, "btnSubmit")
JURISDICTION     = (By.ID, "dropdown")   # value "Hesse" = Berlin
CATEGORY_SELECT  = (By.ID, "category")  # value "1" = OCI
SERVICE_SELECT   = (By.ID, "service")   # value "20" = Fresh OCI
DATE_INPUT       = (By.ID, "appmnt_date")
TIME_SLOT_RADIOS = "input[name='appmnt_time'][type='radio']"
ADDRESS_FIELD    = (By.ID, "address")
CAPTCHA_ANSWER   = (By.ID, "txtCaptcha")   # plain-text answer in hidden field
CAPTCHA_INPUT    = (By.ID, "CaptchaInput") # type answer here
BOOK_BUTTON      = (By.ID, "btnSubmitReq")
AVAILABLE_CELLS  = "#ui-datepicker-div td:not(.ui-datepicker-unselectable):not(.ui-datepicker-other-month) a"
BOOKED_CELLS     = "#ui-datepicker-div td.booked-dates"
```

## GitHub Configuration

### Secrets (sensitive — never expose)
| Secret | Value |
|--------|-------|
| `NTFY_TOPIC` | ntfy.sh topic name |
| `APP_REF_NO` | OCI application reference number |
| `PASSPORT_NUMBER` | Passport number |
| `FIRST_NAME` | Applicant first name |
| `LAST_NAME` | Applicant last name |
| `DATE_OF_BIRTH` | DOB in `MM/DD/YYYY` format |
| `MOBILE_NUMBER` | Mobile with country code |
| `EMAIL` | Booking email |
| `NATIONALITY_VALUE` | Dropdown value for nationality (82 = Romanian) |
| `ADDRESS` | Street address for booking form |

### Variables (changeable without code deploy)
| Variable | Current Value | Purpose |
|----------|---------------|---------|
| `CUTOFF_DATE` | `2026-11-20` | Don't book slots on/after this date (existing appointment date) |
| `CANCEL_COUNT` | `0` | How many times appointment has been cancelled (max 2) |

**Important**: `CUTOFF_DATE` in GitHub (`2026-11-20`) differs from `.env.local` (`2026-12-25`). GitHub runs stop scanning at November; local runs scan through December.

## Trigger Setup

- **GitHub Actions schedule**: removed — do NOT add a `schedule:` trigger back
- **Trigger**: cron-job.org calls GitHub API every 2 minutes to fire `workflow_dispatch`
- Workflow only has `on: workflow_dispatch`

## Notifications (ntfy.sh)

All notifications now include a tappable GitHub Actions run URL (`🔗 Run #N: https://...`) for direct log access.

Notification titles:
- `OCI Appointment Booked!` — success, check email
- `OCI Slot Taken Before Booking` — slot grabbed by someone else, keep monitoring
- `OCI Slot Found — Cancel Your Current Appointment!` — already_booked outcome
- `OCI Auto-Book Failed — Check Logs` — error during booking
- `OCI Slot Available! (N date(s))` — slots found but outside 30-day auto-book window

## Dos

- **Update `CUTOFF_DATE`** in GitHub Variables after every successful booking (set it to the new appointment date)
- **Increment `CANCEL_COUNT`** in GitHub Variables each time you cancel an appointment
- **Run locally** with `bash run_test.sh` for visual testing (browser stays open 40s before submit)
- **Check the screenshot artifact** in GitHub Actions → run → Artifacts for visual debugging
- When running locally, use `pkill -f chromedriver` first to avoid leftover processes

## Don'ts

- **Never add `schedule:` trigger** to the workflow — cron-job.org is the sole trigger
- **Never let `CANCEL_COUNT` reach 2** without resetting — passport gets blocked for 2 weeks
- **Never hardcode personal details** in the script — always via environment variables
- **Don't run many local instances simultaneously** — the embassy site rate-limits by IP; too many rapid runs cause `RemoteDisconnected` errors
- **Don't add `time.sleep()`** — all waits are explicit WebDriverWait conditions; sleeps slow down booking

## Gotchas

- **DOB field uses jQuery datepicker**: set via JS (`el.value = ...`) then trigger `jQuery(el).trigger('change')` with fallback to native `dispatchEvent` — plain `send_keys` doesn't work
- **CAPTCHA is plain text**: the answer is in `#txtCaptcha` (hidden field), type it into `#CaptchaInput`
- **Time slot radios** (`input[name='appmnt_time']`) appear after clicking a date — must be selected before submitting
- **Calendar navigation**: wait for month label to change after clicking next, not a fixed sleep
- **Early exit from scan loop**: script breaks immediately when a within-30-day slot is found — don't add any continue-scanning logic after finding a bookable slot
- **Booking result detection**: site uses SweetAlert2 popups (`.swal2-popup`) — check these before checking URL
- **GitHub vs local CUTOFF_DATE mismatch**: GitHub sees Nov slots and stops; local sees Dec 9/10/11 — they behave differently by design
- **Screenshot artifact**: all per-step PNGs are stitched into one `run_summary.png` uploaded as a GitHub Actions artifact (7-day retention)
- **`/tmp/oci_screenshots`** is cleared at the start of each local run to avoid Pillow DecompressionBombWarning from accumulated large images

## Local Development

```bash
# Copy and fill in your values
cp .env.local.example .env.local   # (no example exists — create manually)

# Run headless check
set -a && source .env.local && set +a && python3 oci_checker.py

# Run visual booking test (browser visible, pauses 40s before submit)
bash run_test.sh
```

`.env.local` format:
```
CUTOFF_DATE=2026-12-25
CANCEL_COUNT=0
APP_REF_NO=...
PASSPORT_NUMBER=...
FIRST_NAME=...
LAST_NAME=...
DATE_OF_BIRTH=MM/DD/YYYY
MOBILE_NUMBER=...
EMAIL=...
NATIONALITY_VALUE=82
ADDRESS="Street, City, PostalCode"
```
