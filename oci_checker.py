"""
OCI Appointment Checker — Embassy of India, Berlin
Checks https://appointment.indianembassyberlin.gov.in for available Fresh OCI slots.

Flow (verified against the live site):
  Page 1 (/):                    agree checkbox + PROCEED
  Page 2 (/applicationscountry): select Jurisdiction=Berlin + agree + PROCEED
  Page 3 (/application):         select Service=OCI, SubType=Fresh OCI,
                                 click date picker, read available dates

Usage:
    python3 oci_checker.py           # headless mode (default)
    python3 oci_checker.py --visible # visible browser window
"""

import os
import sys
import time
import datetime
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "https://appointment.indianembassyberlin.gov.in"

# ── Selectors (verified on 2026-09-06) ──────────────────────────────────────
# Page 1 & 2
AGREE_CHECKBOX      = (By.ID, "agree")
PROCEED_BUTTON      = (By.ID, "btnSubmit")

# Page 2
JURISDICTION_SELECT = (By.ID, "dropdown")   # name='state'
BERLIN_VALUE        = "Hesse"               # text='Berlin'

# Page 3 (/application)
CATEGORY_SELECT     = (By.ID, "category")   # name='category'
OCI_CATEGORY_VALUE  = "1"                   # text='OCI Services'
SERVICE_SELECT      = (By.ID, "service")    # name='service', loaded dynamically
FRESH_OCI_VALUE     = "20"                  # text='Fresh OCI'
DATE_INPUT          = (By.ID, "appmnt_date")  # jQuery UI datepicker, name='appmnt_date'

# Calendar — jQuery UI datepicker
CALENDAR_DIV        = "#ui-datepicker-div"
# Available: td cells that CAN be clicked (have an <a> inside, not unselectable)
AVAILABLE_CELLS     = "#ui-datepicker-div td:not(.ui-datepicker-unselectable):not(.ui-datepicker-other-month) a"
BOOKED_CELLS        = "#ui-datepicker-div td.booked-dates"
ALL_CELLS           = "#ui-datepicker-div td:not(.ui-datepicker-other-month)"
NEXT_MONTH_BTN      = "#ui-datepicker-div .ui-datepicker-next"
MONTH_YEAR_LABEL    = "#ui-datepicker-div .ui-datepicker-title"
# ─────────────────────────────────────────────────────────────────────────────

MONTHS_TO_CHECK = 5   # max months to scan — stops early if CUTOFF_DATE is reached

# Set CUTOFF_DATE env var (YYYY-MM-DD) to only alert for slots before that date.
# Configurable via GitHub Actions Variables without any code change.
_cutoff_str = os.environ.get("CUTOFF_DATE", "").strip()
try:
    CUTOFF_DATE = datetime.date.fromisoformat(_cutoff_str) if _cutoff_str else None
except ValueError:
    print(f"WARNING: Invalid CUTOFF_DATE '{_cutoff_str}', ignoring.")
    CUTOFF_DATE = None


def build_driver(visible: bool) -> webdriver.Chrome:
    opts = Options()
    if not visible:
        opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1280,900")
    else:
        opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    svc = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=svc, options=opts)


def agree_and_proceed(driver, wait):
    """Check #agree if present + click #btnSubmit (waiting for it to be enabled)."""
    try:
        chk = wait.until(EC.presence_of_element_located(AGREE_CHECKBOX))
        if not chk.is_selected():
            chk.click()
        time.sleep(0.3)
    except Exception:
        pass  # checkbox not always present

    btn = wait.until(EC.element_to_be_clickable(PROCEED_BUTTON))
    btn.click()
    time.sleep(2)


def get_available_dates(driver, month_label: str) -> list[str]:
    """Return list of available date strings in the currently shown month,
    filtered to only include dates before CUTOFF_DATE if set."""
    available = []
    cells = driver.find_elements(By.CSS_SELECTOR, AVAILABLE_CELLS)
    for cell in cells:
        day = cell.text.strip()
        if not day:
            continue
        if CUTOFF_DATE:
            try:
                cell_date = datetime.datetime.strptime(
                    f"{month_label} {day}", "%B %Y %d"
                ).date()
                if cell_date >= CUTOFF_DATE:
                    continue  # skip — not earlier than current appointment
            except ValueError:
                pass
        available.append(f"{month_label} {day}")
    return available


MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]


def get_month_label(driver) -> str:
    """Extract 'Month YYYY' from the jQuery UI datepicker header."""
    try:
        # When the datepicker uses <select> dropdowns for month/year
        m_sel = driver.find_elements(By.CSS_SELECTOR,
                                     "#ui-datepicker-div select.ui-datepicker-month")
        y_sel = driver.find_elements(By.CSS_SELECTOR,
                                     "#ui-datepicker-div select.ui-datepicker-year")
        if m_sel and y_sel:
            month_val = int(Select(m_sel[0]).first_selected_option.get_attribute("value"))
            year_val  = Select(y_sel[0]).first_selected_option.get_attribute("value")
            return f"{MONTH_NAMES[month_val]} {year_val}"

        # When the datepicker shows plain text spans
        m_span = driver.find_elements(By.CSS_SELECTOR,
                                      "#ui-datepicker-div .ui-datepicker-month")
        y_span = driver.find_elements(By.CSS_SELECTOR,
                                      "#ui-datepicker-div .ui-datepicker-year")
        if m_span and y_span:
            return f"{m_span[0].text.strip()} {y_span[0].text.strip()}"

        # Fallback: title text first line
        title = driver.find_element(By.CSS_SELECTOR,
                                    "#ui-datepicker-div .ui-datepicker-title")
        return title.text.split("\n")[0].strip()
    except Exception:
        return "Unknown month"


def summarise_month(driver) -> tuple[str, list[str], int, int]:
    """Return (month_label, available_dates, booked_count, total_count)."""
    label = get_month_label(driver)

    available = get_available_dates(driver, label)

    booked  = driver.find_elements(By.CSS_SELECTOR, BOOKED_CELLS)
    all_td  = driver.find_elements(By.CSS_SELECTOR, ALL_CELLS)
    return label, available, len(booked), len(all_td)


def notify(available_dates: list[str]):
    """Send a push notification via ntfy.sh with the available dates."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    dates_str = "\n".join(f"• {d}" for d in available_dates)
    cutoff_line = f"Earlier than your appointment on {CUTOFF_DATE}\n\n" if CUTOFF_DATE else ""
    message = f"Fresh OCI slots open in Berlin!\n\n{cutoff_line}{dates_str}\n\nBook at: {BASE_URL}"
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": f"OCI Slot Available! ({len(available_dates)} date(s))",
                "Priority": "urgent",
                "Tags": "tada,calendar",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"  Notification sent to ntfy topic '{topic}'")
    except Exception as e:
        print(f"  Notification failed: {e}")


def run_check(visible: bool = False):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] Starting OCI slot check…")
    driver = build_driver(visible)
    wait   = WebDriverWait(driver, 20)

    try:
        # ── Step 1: Homepage ────────────────────────────────────────────
        driver.get(BASE_URL)
        wait.until(EC.presence_of_element_located(AGREE_CHECKBOX))
        print("  Page 1 loaded — agreeing to terms and proceeding…")
        agree_and_proceed(driver, wait)

        # ── Step 2: Select Jurisdiction = Berlin ────────────────────────
        wait.until(EC.presence_of_element_located(JURISDICTION_SELECT))
        print("  Page 2 loaded — selecting Berlin…")
        Select(driver.find_element(*JURISDICTION_SELECT)).select_by_value(BERLIN_VALUE)
        time.sleep(0.5)
        agree_and_proceed(driver, wait)

        # ── Step 3: Select OCI category ─────────────────────────────────
        wait.until(EC.presence_of_element_located(CATEGORY_SELECT))
        print("  Page 3 (/application) loaded — selecting OCI Services…")
        Select(driver.find_element(*CATEGORY_SELECT)).select_by_value(OCI_CATEGORY_VALUE)

        # Wait for the #service select to appear (loaded via AJAX/JS)
        wait.until(EC.presence_of_element_located(SERVICE_SELECT))
        time.sleep(0.5)

        # ── Step 4: Select Fresh OCI ─────────────────────────────────────
        print("  Selecting Fresh OCI…")
        svc_sel = driver.find_element(*SERVICE_SELECT)
        Select(svc_sel).select_by_value(FRESH_OCI_VALUE)
        time.sleep(0.5)

        # ── Step 5: Open date picker ─────────────────────────────────────
        print("  Opening appointment date picker…")
        date_inp = wait.until(EC.element_to_be_clickable(DATE_INPUT))
        date_inp.click()

        # Wait for calendar to render
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, CALENDAR_DIV)))
        time.sleep(0.5)

        # ── Step 6: Scan calendar months ─────────────────────────────────
        all_available: list[str] = []

        for month_idx in range(MONTHS_TO_CHECK):
            label, avail, booked_cnt, total_cnt = summarise_month(driver)

            # Stop if this entire month is on/after the cutoff date
            if CUTOFF_DATE:
                try:
                    month_start = datetime.datetime.strptime(
                        f"{label} 1", "%B %Y %d"
                    ).date()
                    if month_start >= CUTOFF_DATE:
                        print(f"\n  Stopping at {label} — on/after cutoff {CUTOFF_DATE}")
                        break
                except ValueError:
                    pass

            print(f"\n  Month: {label}")
            print(f"    Total working days: {total_cnt - booked_cnt} "
                  f"(booked={booked_cnt}, total cells={total_cnt})")

            if avail:
                print(f"    AVAILABLE slots ({len(avail)}):")
                for d in avail:
                    print(f"      • {d}")
                all_available.extend(avail)
            else:
                print("    No available slots.")

            # Navigate to next month (unless it's the last iteration)
            if month_idx < MONTHS_TO_CHECK - 1:
                try:
                    next_btn = wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, NEXT_MONTH_BTN))
                    )
                    next_btn.click()
                    time.sleep(0.8)
                except Exception:
                    break  # no more months available

        # ── Summary ───────────────────────────────────────────────────────
        print(f"\n{'='*50}")
        if all_available:
            print(f"AVAILABLE OCI appointment dates found ({len(all_available)} total):")
            for d in all_available:
                print(f"  • {d}")
            print(f"\nBook at: {BASE_URL}")
            notify(all_available)
        else:
            cutoff_info = f" before {CUTOFF_DATE}" if CUTOFF_DATE else ""
            print(f"No available OCI appointment slots found{cutoff_info}.")
        print(f"{'='*50}")

        if visible:
            print("\nBrowser stays open for 30s — inspect the page manually…")
            time.sleep(30)

        return all_available  # non-empty = slots found

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return None  # signals an error
    finally:
        driver.quit()


if __name__ == "__main__":
    visible = "--visible" in sys.argv
    result = run_check(visible=visible)
    if result is None:
        sys.exit(2)   # error
    elif result:
        sys.exit(1)   # slots found — lets GitHub Actions detect and notify
    else:
        sys.exit(0)   # no slots, all good
