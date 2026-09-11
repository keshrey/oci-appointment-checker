"""
Test script — runs the full booking flow visibly and stops just before
clicking 'Book An Appointment'. For visual inspection only.
"""

import os, sys, time, datetime
sys.path.insert(0, os.path.dirname(__file__))

# Load personal details from environment (same as production)
os.environ.setdefault("CUTOFF_DATE", "2026-11-20")
os.environ.setdefault("CANCEL_COUNT", "0")

from oci_checker import (
    build_driver, agree_and_proceed, get_month_label,
    get_available_dates, AVAILABLE_CELLS, NEXT_MONTH_BTN,
    JURISDICTION_SELECT, BERLIN_VALUE, CATEGORY_SELECT, OCI_CATEGORY_VALUE,
    SERVICE_SELECT, FRESH_OCI_VALUE, DATE_INPUT, CALENDAR_DIV,
    AGREE_CHECKBOX, MONTHS_TO_CHECK, navigate_datepicker_to_month,
    fill_form_fields, CAPTCHA_ANSWER, BOOK_BUTTON,
    BASE_URL, PERSONAL, select_first_time_slot,
)
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

def main():
    print("Starting VISIBLE test flow — will stop before submitting.\n")
    driver = build_driver(visible=True)
    wait   = WebDriverWait(driver, 20)

    try:
        # ── Page 1 ────────────────────────────────────────────────────────────
        driver.get(BASE_URL)
        wait.until(EC.presence_of_element_located(AGREE_CHECKBOX))
        print("Page 1 loaded — agreeing and proceeding…")
        agree_and_proceed(driver, wait)

        # ── Page 2 ────────────────────────────────────────────────────────────
        wait.until(EC.presence_of_element_located(JURISDICTION_SELECT))
        print("Page 2 loaded — selecting Berlin…")
        Select(driver.find_element(*JURISDICTION_SELECT)).select_by_value(BERLIN_VALUE)
        time.sleep(0.5)
        agree_and_proceed(driver, wait)

        # ── Page 3 ────────────────────────────────────────────────────────────
        wait.until(EC.presence_of_element_located(CATEGORY_SELECT))
        print("Page 3 loaded — selecting OCI Services…")
        Select(driver.find_element(*CATEGORY_SELECT)).select_by_value(OCI_CATEGORY_VALUE)
        wait.until(EC.presence_of_element_located(SERVICE_SELECT))
        time.sleep(0.5)
        Select(driver.find_element(*SERVICE_SELECT)).select_by_value(FRESH_OCI_VALUE)
        time.sleep(0.5)

        # ── Find first available date ─────────────────────────────────────────
        print("Opening datepicker to find first available date…")
        date_inp = wait.until(EC.element_to_be_clickable(DATE_INPUT))
        date_inp.click()
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, CALENDAR_DIV)))
        time.sleep(0.5)

        target_date = None
        target_display = None

        for _ in range(MONTHS_TO_CHECK):
            label = get_month_label(driver)
            slots = get_available_dates(driver, label)
            if slots:
                target_display, target_date = slots[0]
                print(f"First available slot: {target_display}")
                break
            try:
                next_btn = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, NEXT_MONTH_BTN)))
                next_btn.click()
                time.sleep(0.5)
            except Exception:
                break

        if not target_date:
            print("No available slots found to test with!")
            time.sleep(10)
            return

        # ── Navigate datepicker to target month and click date ────────────────
        print(f"\nNavigating to {target_date}…")
        if not navigate_datepicker_to_month(driver, wait, target_date):
            # Re-open datepicker if needed
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            time.sleep(0.3)
            date_inp = wait.until(EC.element_to_be_clickable(DATE_INPUT))
            date_inp.click()
            wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, CALENDAR_DIV)))
            time.sleep(0.5)
            navigate_datepicker_to_month(driver, wait, target_date)

        day_str = str(target_date.day)
        for cell in driver.find_elements(By.CSS_SELECTOR, AVAILABLE_CELLS):
            if cell.text.strip() == day_str:
                cell.click()
                print(f"Clicked date: {target_display}")
                time.sleep(0.8)
                select_first_time_slot(driver, wait)
                break

        date_val = driver.find_element(*DATE_INPUT).get_attribute("value")
        print(f"Date field set to: {date_val!r}")

        # ── Fill all personal fields ──────────────────────────────────────────
        print("\nFilling personal details…")
        fill_form_fields(driver, wait)

        captcha_val = driver.find_element(*CAPTCHA_ANSWER).get_attribute("value")
        print(f"\nAll fields filled. Captcha answer was: {captcha_val}")
        print("\n" + "="*50)
        print("STOPPING HERE — 'Book An Appointment' button NOT clicked.")
        print("Inspect the form in the browser.")
        print("="*50)

        print("\nBrowser stays open for 40s…")
        time.sleep(40)

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
