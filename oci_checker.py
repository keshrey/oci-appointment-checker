"""
OCI Appointment Checker & Auto-Booker — Embassy of India, Berlin

Flow (verified against the live site):
  Page 1 (/):                    agree checkbox + PROCEED
  Page 2 (/applicationscountry): select Jurisdiction=Berlin + agree + PROCEED
  Page 3 (/application):         select OCI, Fresh OCI, scan datepicker

Auto-booking logic:
  - Slot within AUTO_BOOK_DAYS  → attempt to book automatically
  - Slot beyond AUTO_BOOK_DAYS  → send notification only
  - CANCEL_COUNT >= 2           → notification only (never risk passport block)
  - Already has appointment     → notify user to cancel manually first

Usage:
    python3 oci_checker.py           # headless
    python3 oci_checker.py --visible # visible browser
"""

import os
import sys
import time
import datetime
import urllib.request
import urllib.parse
import pathlib

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

BASE_URL = "https://appointment.indianembassyberlin.gov.in"

# ── Selectors ────────────────────────────────────────────────────────────────
AGREE_CHECKBOX      = (By.ID, "agree")
PROCEED_BUTTON      = (By.ID, "btnSubmit")
JURISDICTION_SELECT = (By.ID, "dropdown")
BERLIN_VALUE        = "Hesse"
CATEGORY_SELECT     = (By.ID, "category")
OCI_CATEGORY_VALUE  = "1"
SERVICE_SELECT      = (By.ID, "service")
FRESH_OCI_VALUE     = "20"
DATE_INPUT          = (By.ID, "appmnt_date")
NATIONALITY_SELECT  = (By.ID, "nationality")
CALENDAR_DIV        = "#ui-datepicker-div"
AVAILABLE_CELLS     = "#ui-datepicker-div td:not(.ui-datepicker-unselectable):not(.ui-datepicker-other-month) a"
BOOKED_CELLS        = "#ui-datepicker-div td.booked-dates"
ALL_CELLS           = "#ui-datepicker-div td:not(.ui-datepicker-other-month)"
NEXT_MONTH_BTN      = "#ui-datepicker-div .ui-datepicker-next"
BOOK_BUTTON         = (By.ID, "btnSubmitReq")
CAPTCHA_ANSWER      = (By.ID, "txtCaptcha")
CAPTCHA_INPUT       = (By.ID, "CaptchaInput")
TIME_SLOT_RADIOS    = "input[name='appmnt_time'][type='radio']"
ADDRESS_FIELD       = (By.ID, "address")
# ─────────────────────────────────────────────────────────────────────────────

MONTHS_TO_CHECK   = 5
AUTO_BOOK_DAYS    = 30   # auto-book if slot is within this many days from today

MONTH_NAMES = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]

# ── Config from environment ──────────────────────────────────────────────────
_cutoff_str = os.environ.get("CUTOFF_DATE", "").strip()
try:
    CUTOFF_DATE = datetime.date.fromisoformat(_cutoff_str) if _cutoff_str else None
except ValueError:
    print(f"WARNING: Invalid CUTOFF_DATE '{_cutoff_str}', ignoring.")
    CUTOFF_DATE = None

try:
    CANCEL_COUNT = int(os.environ.get("CANCEL_COUNT", "0"))
except ValueError:
    CANCEL_COUNT = 0

PERSONAL = {
    "app_ref_no":   os.environ.get("APP_REF_NO", ""),
    "passport":     os.environ.get("PASSPORT_NUMBER", ""),
    "first_name":   os.environ.get("FIRST_NAME", ""),
    "last_name":    os.environ.get("LAST_NAME", ""),
    "dob":          os.environ.get("DATE_OF_BIRTH", ""),
    "mobile":       os.environ.get("MOBILE_NUMBER", ""),
    "email":        os.environ.get("EMAIL", ""),
    "nationality":  os.environ.get("NATIONALITY_VALUE", ""),
    "address":      os.environ.get("ADDRESS", ""),
}
# ─────────────────────────────────────────────────────────────────────────────


SCREENSHOT_DIR = pathlib.Path("/tmp/oci_screenshots")
_shot_index = 0

def screenshot(driver, label: str):
    global _shot_index
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{_shot_index:02d}_{label}.png"
    driver.save_screenshot(str(path))
    _shot_index += 1
    print(f"  [screenshot] {path.name}")


def stitch_screenshots() -> pathlib.Path | None:
    """Combine all screenshots in SCREENSHOT_DIR into one tall PNG."""
    try:
        from PIL import Image
        images = sorted(SCREENSHOT_DIR.glob("*.png"))
        if not images:
            return None
        imgs = [Image.open(p) for p in images]
        max_w = max(i.width for i in imgs)
        total_h = sum(i.height for i in imgs)
        combined = Image.new("RGB", (max_w, total_h), (255, 255, 255))
        y = 0
        for img in imgs:
            combined.paste(img, (0, y))
            y += img.height
        out = SCREENSHOT_DIR / "run_summary.png"
        combined.save(str(out))
        print(f"  Combined screenshot: {out}")
        return out
    except Exception as e:
        print(f"  Could not stitch screenshots: {e}")
        return None


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
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_page_load_timeout(60)
    return driver


def agree_and_proceed(driver, wait):
    try:
        chk = wait.until(EC.presence_of_element_located(AGREE_CHECKBOX))
        if not chk.is_selected():
            chk.click()
        time.sleep(0.3)
    except Exception:
        pass
    btn = wait.until(EC.element_to_be_clickable(PROCEED_BUTTON))
    btn.click()
    time.sleep(2)


def get_month_label(driver) -> str:
    try:
        m_sel = driver.find_elements(By.CSS_SELECTOR,
                                     "#ui-datepicker-div select.ui-datepicker-month")
        y_sel = driver.find_elements(By.CSS_SELECTOR,
                                     "#ui-datepicker-div select.ui-datepicker-year")
        if m_sel and y_sel:
            month_val = int(Select(m_sel[0]).first_selected_option.get_attribute("value"))
            year_val  = Select(y_sel[0]).first_selected_option.get_attribute("value")
            return f"{MONTH_NAMES[month_val]} {year_val}"
        m_span = driver.find_elements(By.CSS_SELECTOR, "#ui-datepicker-div .ui-datepicker-month")
        y_span = driver.find_elements(By.CSS_SELECTOR, "#ui-datepicker-div .ui-datepicker-year")
        if m_span and y_span:
            return f"{m_span[0].text.strip()} {y_span[0].text.strip()}"
        title = driver.find_element(By.CSS_SELECTOR, "#ui-datepicker-div .ui-datepicker-title")
        return title.text.split("\n")[0].strip()
    except Exception:
        return "Unknown month"


def parse_slot_date(month_label: str, day: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(f"{month_label} {day}", "%B %Y %d").date()
    except ValueError:
        return None


def get_available_dates(driver, month_label: str) -> list[tuple[str, datetime.date]]:
    """Return list of (display_str, date) for available slots, filtered by CUTOFF_DATE."""
    available = []
    for cell in driver.find_elements(By.CSS_SELECTOR, AVAILABLE_CELLS):
        day = cell.text.strip()
        if not day:
            continue
        slot_date = parse_slot_date(month_label, day)
        if slot_date is None:
            continue
        if CUTOFF_DATE and slot_date >= CUTOFF_DATE:
            continue
        available.append((f"{month_label} {day}", slot_date))
    return available


def is_within_auto_book_window(slot_date: datetime.date) -> bool:
    return slot_date <= datetime.date.today() + datetime.timedelta(days=AUTO_BOOK_DAYS)


def notify(title: str, message: str, priority: str = "urgent"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Tags": "tada,calendar"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        print(f"  Notification sent: {title}")
    except Exception as e:
        print(f"  Notification failed: {e}")


# ── Auto-booking ─────────────────────────────────────────────────────────────

def select_first_time_slot(driver, wait) -> bool:
    """Click the first available time-slot radio button after a date is selected."""
    try:
        WebDriverWait(driver, 5).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, TIME_SLOT_RADIOS)
        )
        radios = driver.find_elements(By.CSS_SELECTOR, TIME_SLOT_RADIOS)
        if radios:
            driver.execute_script("arguments[0].click();", radios[0])
            label = radios[0].find_elements(By.XPATH, "following-sibling::label")
            slot_text = label[0].text.strip() if label else radios[0].get_attribute("value")
            print(f"  Time slot selected: {slot_text}")
            time.sleep(0.3)
            return True
    except Exception:
        pass
    print("  No time slot radios found (may not have appeared yet)")
    return False


def navigate_datepicker_to_month(driver, wait, target_date: datetime.date) -> bool:
    """Navigate the open datepicker to the month containing target_date."""
    for _ in range(12):
        label = get_month_label(driver)
        try:
            month_start = datetime.datetime.strptime(f"{label} 1", "%B %Y %d").date()
            if month_start.year == target_date.year and month_start.month == target_date.month:
                return True
            if month_start > target_date:
                return False
        except ValueError:
            return False
        try:
            next_btn = wait.until(EC.element_to_be_clickable(
                (By.CSS_SELECTOR, NEXT_MONTH_BTN)))
            next_btn.click()
            time.sleep(0.5)
        except Exception:
            return False
    return False


def select_date_in_picker(driver, wait, target_date: datetime.date) -> bool:
    """Open datepicker, navigate to month, click the day. Returns True on success."""
    date_inp = wait.until(EC.element_to_be_clickable(DATE_INPUT))
    date_inp.click()
    wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, CALENDAR_DIV)))
    time.sleep(0.5)

    if not navigate_datepicker_to_month(driver, wait, target_date):
        print(f"  Could not navigate datepicker to {target_date}")
        return False

    day_str = str(target_date.day)
    for cell in driver.find_elements(By.CSS_SELECTOR, AVAILABLE_CELLS):
        if cell.text.strip() == day_str:
            cell.click()
            time.sleep(0.8)
            select_first_time_slot(driver, wait)
            return True

    print(f"  Day {day_str} not found / no longer available in datepicker")
    return False


def fill_form_fields(driver, wait):
    """Fill all personal detail fields."""
    def set_field(field_id, value):
        if not value:
            return
        el = driver.find_element(By.ID, field_id)
        el.clear()
        el.send_keys(value)
        time.sleep(0.1)

    set_field("app_ref_no",     PERSONAL["app_ref_no"])
    set_field("passport_number", PERSONAL["passport"])
    set_field("firstname",       PERSONAL["first_name"])
    set_field("secondname",      PERSONAL["last_name"])
    set_field("mobile_number",   PERSONAL["mobile"])
    set_field("email",           PERSONAL["email"])
    set_field("address",         PERSONAL["address"])

    # DOB — jQuery datepicker field; set via JS then trigger change
    if PERSONAL["dob"]:
        driver.execute_script(
            "var el = document.getElementById('date_of_birth');"
            "el.value = arguments[0];"
            "if(typeof jQuery !== 'undefined') jQuery(el).trigger('change');"
            "else el.dispatchEvent(new Event('change', {bubbles:true}));",
            PERSONAL["dob"]
        )
        time.sleep(0.2)

    # Nationality
    if PERSONAL["nationality"]:
        try:
            Select(driver.find_element(*NATIONALITY_SELECT)).select_by_value(
                PERSONAL["nationality"])
            time.sleep(0.3)
        except Exception as e:
            print(f"  Warning: could not set nationality: {e}")

    # Captcha — answer is in hidden field #txtCaptcha
    captcha_val = driver.find_element(*CAPTCHA_ANSWER).get_attribute("value")
    print(f"  Captcha answer: {captcha_val}")
    cap_inp = driver.find_element(*CAPTCHA_INPUT)
    cap_inp.clear()
    cap_inp.send_keys(captcha_val)
    time.sleep(0.2)


def detect_result(driver, wait) -> tuple[str, str]:
    """
    Wait for booking result. Returns (status, message):
      'success'           — booking confirmed
      'already_booked'    — user already has an active appointment
      'slot_gone'         — date no longer available
      'error'             — other failure
    """
    try:
        # Wait up to 10s for SweetAlert or page change
        wait_short = WebDriverWait(driver, 10)
        wait_short.until(lambda d:
            d.find_elements(By.CSS_SELECTOR, ".swal2-popup") or
            d.find_elements(By.CSS_SELECTOR, ".swal2-container") or
            "success" in d.current_url.lower() or
            "confirm" in d.current_url.lower()
        )
    except Exception:
        pass

    # Check SweetAlert
    for sel in [".swal2-html-container", ".swal2-content", ".swal2-popup"]:
        els = driver.find_elements(By.CSS_SELECTOR, sel)
        if els:
            text = els[0].text.strip().lower()
            print(f"  Site response: {els[0].text.strip()[:200]}")
            if any(w in text for w in ["success", "booked", "confirm", "appointment has been"]):
                return "success", els[0].text.strip()
            if any(w in text for w in ["already", "existing", "have an appointment", "active booking"]):
                return "already_booked", els[0].text.strip()
            if any(w in text for w in ["not available", "slot", "taken", "unavailable"]):
                return "slot_gone", els[0].text.strip()
            return "error", els[0].text.strip()

    # Check URL
    if any(w in driver.current_url.lower() for w in ["success", "confirm"]):
        return "success", "Booking confirmed (URL redirect)"

    return "error", f"Unknown result. URL: {driver.current_url}"


def attempt_auto_book(driver, wait, target_date: datetime.date, display_str: str) -> str:
    """
    Try to book target_date. Returns outcome string.
    Pre-condition: driver is on the /application page with OCI + Fresh OCI selected.
    """
    print(f"\n  AUTO-BOOKING: attempting to book {display_str}…")

    # Step 1: Select the date in the datepicker
    if not select_date_in_picker(driver, wait, target_date):
        return "slot_gone"

    # Verify the date got set
    date_val = driver.find_element(*DATE_INPUT).get_attribute("value")
    print(f"  Date field value: {date_val!r}")
    if not date_val:
        return "slot_gone"

    # Step 2: Fill personal details + captcha
    fill_form_fields(driver, wait)

    # Step 3: Submit
    print("  Clicking 'Book An Appointment'…")
    try:
        btn = wait.until(EC.element_to_be_clickable(BOOK_BUTTON))
        btn.click()
    except Exception as e:
        print(f"  Could not click book button: {e}")
        return "error"

    # Step 4: Detect result
    status, msg = detect_result(driver, wait)
    print(f"  Booking result: {status} — {msg[:100]}")
    return status


# ── Main check ───────────────────────────────────────────────────────────────

def run_check(visible: bool = False):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] Starting OCI slot check…")
    if CUTOFF_DATE:
        print(f"  Cutoff: {CUTOFF_DATE}  |  Cancel count: {CANCEL_COUNT}/2  |  "
              f"Auto-book window: {AUTO_BOOK_DAYS} days")

    driver = build_driver(visible)
    wait   = WebDriverWait(driver, 20)

    try:
        # ── Navigate to /application ─────────────────────────────────────────
        driver.get(BASE_URL)
        wait.until(EC.presence_of_element_located(AGREE_CHECKBOX))
        print("  Page 1 — agreeing and proceeding…")
        screenshot(driver, "page1_agree")
        agree_and_proceed(driver, wait)

        wait.until(EC.presence_of_element_located(JURISDICTION_SELECT))
        print("  Page 2 — selecting Berlin…")
        screenshot(driver, "page2_jurisdiction")
        Select(driver.find_element(*JURISDICTION_SELECT)).select_by_value(BERLIN_VALUE)
        time.sleep(0.5)
        agree_and_proceed(driver, wait)

        wait.until(EC.presence_of_element_located(CATEGORY_SELECT))
        print("  Page 3 — selecting OCI Services…")
        Select(driver.find_element(*CATEGORY_SELECT)).select_by_value(OCI_CATEGORY_VALUE)
        wait.until(EC.presence_of_element_located(SERVICE_SELECT))
        time.sleep(0.5)

        print("  Selecting Fresh OCI…")
        Select(driver.find_element(*SERVICE_SELECT)).select_by_value(FRESH_OCI_VALUE)
        time.sleep(0.5)
        screenshot(driver, "page3_service_selected")

        # ── Open datepicker and scan months ──────────────────────────────────
        print("  Opening datepicker…")
        date_inp = wait.until(EC.element_to_be_clickable(DATE_INPUT))
        date_inp.click()
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, CALENDAR_DIV)))
        time.sleep(0.5)

        all_available: list[tuple[str, datetime.date]] = []

        for month_idx in range(MONTHS_TO_CHECK):
            label = get_month_label(driver)

            if CUTOFF_DATE:
                try:
                    month_start = datetime.datetime.strptime(f"{label} 1", "%B %Y %d").date()
                    if month_start >= CUTOFF_DATE:
                        print(f"\n  Stopping at {label} — on/after cutoff {CUTOFF_DATE}")
                        break
                except ValueError:
                    pass

            slots = get_available_dates(driver, label)
            booked_cnt = len(driver.find_elements(By.CSS_SELECTOR, BOOKED_CELLS))
            total_cnt  = len(driver.find_elements(By.CSS_SELECTOR, ALL_CELLS))

            print(f"\n  Month: {label}  (booked={booked_cnt}, total={total_cnt})")
            screenshot(driver, f"calendar_{label.replace(' ', '_')}")
            if slots:
                print(f"    AVAILABLE ({len(slots)}):")
                for ds, dt in slots:
                    tag = " ← AUTO-BOOK" if is_within_auto_book_window(dt) else ""
                    print(f"      • {ds}{tag}")
                all_available.extend(slots)
            else:
                print("    No available slots.")

            if month_idx < MONTHS_TO_CHECK - 1:
                try:
                    next_btn = wait.until(EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, NEXT_MONTH_BTN)))
                    next_btn.click()
                    time.sleep(0.8)
                except Exception:
                    break

        # ── Decide: auto-book or notify ───────────────────────────────────────
        print(f"\n{'='*50}")

        if not all_available:
            cutoff_info = f" before {CUTOFF_DATE}" if CUTOFF_DATE else ""
            print(f"No available OCI slots found{cutoff_info}.")
            print(f"{'='*50}")
            return []

        # Separate into auto-book candidates and notify-only
        to_book   = [(ds, dt) for ds, dt in all_available if is_within_auto_book_window(dt)]
        to_notify = [(ds, dt) for ds, dt in all_available if not is_within_auto_book_window(dt)]

        print(f"Slots found — {len(to_book)} within {AUTO_BOOK_DAYS} days, "
              f"{len(to_notify)} beyond.")

        booking_outcome = None

        if to_book:
            # Pick earliest
            to_book.sort(key=lambda x: x[1])
            best_display, best_date = to_book[0]

            if CANCEL_COUNT >= 2:
                print(f"\n  CANCEL_COUNT={CANCEL_COUNT} — skipping auto-book to protect passport.")
                msg = (f"Fresh OCI slot within {AUTO_BOOK_DAYS} days: {best_display}\n\n"
                       f"⚠️ Auto-book SKIPPED — cancellation limit reached (2/2).\n"
                       f"Book manually: {BASE_URL}")
                notify(f"OCI Slot Available — Manual Action Needed!", msg)
                booking_outcome = "limit_reached"
            else:
                # Close the datepicker first (press Escape) before filling form
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.3)

                outcome = attempt_auto_book(driver, wait, best_date, best_display)
                screenshot(driver, "after_booking_attempt")
                booking_outcome = outcome

                if outcome == "success":
                    msg = (f"✅ Booked {best_display}!\n\n"
                           f"Earlier than your previous appointment on {CUTOFF_DATE}.\n"
                           f"Check your email for confirmation.\n\n"
                           f"Remember to cancel your old appointment and update "
                           f"CUTOFF_DATE + CANCEL_COUNT in GitHub.")
                    notify("OCI Appointment Booked!", msg)

                elif outcome == "already_booked":
                    msg = (f"Slot {best_display} is available — within {AUTO_BOOK_DAYS} days!\n\n"
                           f"⚠️ Could not auto-book: you already have an active appointment.\n\n"
                           f"1. Cancel your current appointment manually\n"
                           f"2. Increment CANCEL_COUNT in GitHub Variables\n"
                           f"3. The next run will auto-book this slot (if still available)\n\n"
                           f"Book manually: {BASE_URL}")
                    notify("OCI Slot Found — Cancel Your Current Appointment!", msg, priority="urgent")

                elif outcome == "slot_gone":
                    msg = (f"Slot {best_display} was detected but was taken before booking completed.\n\n"
                           f"Continuing to monitor…")
                    notify("OCI Slot Taken Before Booking", msg, priority="default")

                else:  # error
                    msg = f"Slot {best_display} found but booking failed with an error. Check GitHub Actions logs."
                    notify("OCI Auto-Book Failed — Check Logs", msg)

        # Send notification for slots outside auto-book window
        if to_notify:
            dates_str = "\n".join(f"• {ds}" for ds, _ in to_notify)
            cutoff_line = f"Earlier than your appointment on {CUTOFF_DATE}\n\n" if CUTOFF_DATE else ""
            msg = (f"Fresh OCI slots open in Berlin!\n\n"
                   f"{cutoff_line}"
                   f"These are outside the {AUTO_BOOK_DAYS}-day auto-book window:\n"
                   f"{dates_str}\n\n"
                   f"Book at: {BASE_URL}")
            notify(f"OCI Slot Available! ({len(to_notify)} date(s))", msg)

        print(f"{'='*50}")

        if visible:
            print("\nBrowser stays open 30s…")
            time.sleep(30)

        return all_available

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        try:
            screenshot(driver, "error_state")
        except Exception:
            pass
        return None
    finally:
        try:
            stitch_screenshots()
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    visible = "--visible" in sys.argv
    result = run_check(visible=visible)
    if result is None:
        sys.exit(2)
    elif result:
        sys.exit(1)
    else:
        sys.exit(0)
