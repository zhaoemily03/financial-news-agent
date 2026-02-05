"""
Morgan Stanley Research Portal Scraper

Workflow:
1. Login with credentials (from .env)
2. Click "My Feed" button (top right)
3. Extract report notifications from feed
4. Click each report → scroll to reveal PDF button → download PDF
5. Filter: last 5 days only, skip previously processed

Inherits from BaseScraper for shared cookie/auth/PDF functionality.
"""

import os
import re
import time
import hashlib
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from base_scraper import BaseScraper
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from dateutil import parser as dateparser

load_dotenv()


class MorganStanleyScraper(BaseScraper):
    """Scraper for Morgan Stanley research portal using My Feed"""

    # Required by BaseScraper
    PORTAL_NAME = "morgan_stanley"
    CONTENT_URL = "https://ny.matrix.ms.com/eqr/research/ui/#/home"
    LOGIN_URL = "https://login.matrix.ms.com"
    PDF_STORAGE_DIR = "data/reports/morgan_stanley"

    def __init__(self, headless: bool = True):
        super().__init__(headless=headless)
        self.email = os.getenv('MS_EMAIL')
        self.password = os.getenv('MS_PASSWORD')
        # Verification link for device authentication (one-time use)
        self.verification_link = os.getenv('MS_VERIFY_LINK')

    # ------------------------------------------------------------------
    # Browser setup with login
    # ------------------------------------------------------------------

    def _init_driver(self) -> bool:
        """
        Initialize Chrome WebDriver, attempt login, and verify authentication.

        MS uses email verification links for device authentication.
        """
        if self.driver:
            return True

        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')

        self.driver = webdriver.Chrome(options=chrome_options)
        print(f"[{self.PORTAL_NAME}] Initialized Chrome WebDriver")

        # First, try loading existing cookies
        self.driver.get("https://ny.matrix.ms.com")
        time.sleep(2)

        cookies = self.cookie_manager.get_cookies(self.PORTAL_NAME)
        if cookies:
            for name, value in cookies.items():
                try:
                    self.driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': '.ms.com'
                    })
                except Exception:
                    pass
            print(f"[{self.PORTAL_NAME}] Loaded existing cookies")

        # Navigate to portal
        self.driver.get(self.CONTENT_URL)
        time.sleep(5)

        # Check if already authenticated
        if self._check_authentication():
            print(f"[{self.PORTAL_NAME}] ✓ Already authenticated via cookies")
            return True

        # Try verification link if provided
        if self.verification_link:
            return self._use_verification_link()

        # Try password-based login as fallback
        if self.email and self.password:
            return self._perform_login()

        print(f"[{self.PORTAL_NAME}] ✗ No authentication method available")
        print(f"[{self.PORTAL_NAME}]   Set MS_VERIFY_LINK in .env with your verification link")
        return False

    def _use_verification_link(self) -> bool:
        """Use email verification link to authenticate"""
        try:
            print(f"[{self.PORTAL_NAME}] Using verification link...")

            # Try the link as-is first
            self.driver.get(self.verification_link)
            time.sleep(5)

            # Check if we're authenticated now
            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Verification link worked")
                self._persist_cookies()
                return True

            # If link had 'l' that should be 'I', try swapping
            if 'l' in self.verification_link:
                alt_link = self.verification_link.replace('1894l', '1894I')
                print(f"[{self.PORTAL_NAME}] Trying alternate link (l->I)...")
                self.driver.get(alt_link)
                time.sleep(5)

                if self._check_authentication():
                    print(f"[{self.PORTAL_NAME}] ✓ Alternate verification link worked")
                    self._persist_cookies()
                    return True

            # Navigate to portal after verification
            self.driver.get(self.CONTENT_URL)
            time.sleep(5)

            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Authenticated after verification")
                self._persist_cookies()
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Verification link did not authenticate")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Verification error: {e}")
            return False

    def _perform_login(self) -> bool:
        """Perform login with email/password"""
        try:
            print(f"[{self.PORTAL_NAME}] Attempting login...")

            # Navigate to login page if not already there
            self.driver.get(self.LOGIN_URL)
            time.sleep(3)

            # Look for email/username field
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[name="username"]',
                'input[name="loginfmt"]',
                'input[id="username"]',
                'input[id="email"]',
                '#i0116',  # Microsoft login
            ]

            email_field = None
            for selector in email_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed():
                            email_field = el
                            break
                    if email_field:
                        break
                except:
                    continue

            if not email_field:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find email field")
                return False

            # Enter email
            email_field.clear()
            email_field.send_keys(self.email)
            print(f"[{self.PORTAL_NAME}]   Entered email")
            time.sleep(1)

            # Click next/submit if there's a separate password page
            next_buttons = self.driver.find_elements(By.CSS_SELECTOR,
                'input[type="submit"], button[type="submit"], #idSIButton9, .next-button')
            for btn in next_buttons:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(2)
                    break

            # Look for password field
            password_selectors = [
                'input[type="password"]',
                'input[name="password"]',
                'input[name="passwd"]',
                '#i0118',  # Microsoft login
            ]

            password_field = None
            for selector in password_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed():
                            password_field = el
                            break
                    if password_field:
                        break
                except:
                    continue

            if not password_field:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find password field")
                return False

            # Enter password
            password_field.clear()
            password_field.send_keys(self.password)
            print(f"[{self.PORTAL_NAME}]   Entered password")
            time.sleep(1)

            # Click sign in
            submit_buttons = self.driver.find_elements(By.CSS_SELECTOR,
                'input[type="submit"], button[type="submit"], #idSIButton9, .sign-in-button')
            for btn in submit_buttons:
                if btn.is_displayed():
                    btn.click()
                    print(f"[{self.PORTAL_NAME}]   Clicked sign in")
                    break

            # Wait for redirect/auth
            time.sleep(5)

            # Handle "Stay signed in?" prompt if present
            try:
                stay_signed_in = self.driver.find_elements(By.CSS_SELECTOR,
                    '#idBtn_Back, #idSIButton9, button:contains("Yes"), button:contains("No")')
                for btn in stay_signed_in:
                    if btn.is_displayed() and ('yes' in btn.text.lower() or 'no' in btn.text.lower()):
                        btn.click()
                        time.sleep(2)
                        break
            except:
                pass

            # Navigate to research portal
            self.driver.get(self.CONTENT_URL)
            time.sleep(5)

            # Verify login worked
            if self._check_authentication():
                print(f"[{self.PORTAL_NAME}] ✓ Login successful")
                self._persist_cookies()
                return True
            else:
                print(f"[{self.PORTAL_NAME}] ✗ Login failed - may need manual verification")
                return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Login error: {e}")
            return False

    # ------------------------------------------------------------------
    # Authentication check
    # ------------------------------------------------------------------

    def _check_authentication(self) -> bool:
        """Check if we're authenticated to the research portal"""
        try:
            current_url = self.driver.current_url.lower()
            page_title = self.driver.title.lower()
            page_source = self.driver.page_source.lower()

            # Check URL for login/SSO redirects (strongest signal)
            login_url_indicators = [
                'login.microsoftonline', 'login.ms.com', 'sso', 'saml',
                'oauth', 'authenticate', 'signin'
            ]
            for indicator in login_url_indicators:
                if indicator in current_url:
                    print(f"[{self.PORTAL_NAME}] ✗ Auth check: redirected to login ({indicator})")
                    print(f"  Session cookies expired - manual re-authentication required")
                    return False

            # Check page title
            if 'sign in' in page_title or 'login' in page_title:
                print(f"[{self.PORTAL_NAME}] ✗ Auth check: login page (title: {page_title})")
                return False

            # Signs of being authenticated - MS Research portal elements
            auth_indicators = [
                'my feed', 'equity research', 'logout', 'sign out',
                'preferences', 'saved searches', 'alerts'
            ]
            for indicator in auth_indicators:
                if indicator in page_source:
                    print(f"[{self.PORTAL_NAME}] ✓ Auth check: valid session")
                    return True

            # Check URL - if we're on the research UI, we're likely authenticated
            if '/eqr/research/' in current_url or 'matrix.ms.com' in current_url:
                print(f"[{self.PORTAL_NAME}] ✓ Auth check: on research portal")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Auth check: not on portal (URL: {current_url[:60]})")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Auth check error: {e}")
            return False

    # ------------------------------------------------------------------
    # Navigate to My Feed
    # ------------------------------------------------------------------

    def _navigate_to_notifications(self) -> bool:
        """Click the My Feed button (broadcast icon) - located directly right of search bar"""
        try:
            # Wait for page to fully load - MS portal may have slow JS rendering
            print(f"[{self.PORTAL_NAME}] Waiting for page to load...")
            time.sleep(10)

            # Strategy: Find search bar first, then look for elements to its right
            print(f"[{self.PORTAL_NAME}] Looking for search bar...")

            # Common search bar selectors
            search_selectors = [
                'input[type="search"]',
                'input[type="text"][placeholder*="search" i]',
                'input[placeholder*="search" i]',
                'input[aria-label*="search" i]',
                '[class*="search"] input',
                '[class*="search-bar"]',
                '[class*="searchbar"]',
                '[class*="search-input"]',
            ]

            search_bar = None
            search_pos = None

            for selector in search_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed():
                            search_bar = el
                            search_pos = el.location
                            search_size = el.size
                            print(f"[{self.PORTAL_NAME}] ✓ Found search bar at x={search_pos['x']}, y={search_pos['y']}")
                            break
                    if search_bar:
                        break
                except:
                    continue

            if not search_bar:
                print(f"[{self.PORTAL_NAME}] ✗ Could not find search bar")
                # Fall back to scanning all clickable elements
                return self._fallback_find_feed_button()

            # Find clickable elements to the RIGHT of the search bar (within same row)
            search_right_edge = search_pos['x'] + search_size['width']
            search_y_center = search_pos['y'] + search_size['height'] / 2

            # Find clickable elements to the right of the search bar

            # Get all potentially clickable elements
            all_clickable = self.driver.find_elements(By.CSS_SELECTOR,
                'a, button, [role="button"], i, svg, span[class], div[class*="icon"], div[class*="btn"]')

            candidates = []
            for el in all_clickable:
                try:
                    if el.is_displayed():
                        loc = el.location
                        size = el.size
                        el_y_center = loc['y'] + size['height'] / 2

                        # Element must be to the right of search bar
                        # And roughly on the same horizontal line (within 30px)
                        if loc['x'] > search_right_edge and abs(el_y_center - search_y_center) < 30:
                            classes = el.get_attribute('class') or ''
                            aria = el.get_attribute('aria-label') or ''
                            title = el.get_attribute('title') or ''
                            tag = el.tag_name

                            candidates.append({
                                'element': el,
                                'x': loc['x'],
                                'y': loc['y'],
                                'w': size['width'],
                                'h': size['height'],
                                'tag': tag,
                                'class': classes,
                                'aria': aria,
                                'title': title,
                            })
                except:
                    continue

            # Sort by x position (left to right - first element right of search bar)
            candidates.sort(key=lambda e: e['x'])

            # Look for feed-related keywords first
            feed_keywords = ['feed', 'broadcast', 'rss', 'signal', 'notification',
                             'alert', 'bell', 'subscribe', 'follow', 'myfeed']

            for c in candidates:
                combined = (c['class'] + c['aria'] + c['title']).lower()
                if any(kw in combined for kw in feed_keywords):
                    print(f"[{self.PORTAL_NAME}] ✓ Found feed element by keyword: <{c['tag']}> {c['aria'] or c['title'] or c['class'][:40]}")
                    self.driver.execute_script("arguments[0].click();", c['element'])
                    time.sleep(3)
                    return True

            # If no keyword match, click the first small icon-like element right of search bar
            # (The My Feed button should be the first icon after the search bar)
            for c in candidates:
                # Skip elements that are too large (likely not icons)
                if c['w'] > 80 or c['h'] > 60:
                    continue
                # Skip search-related elements
                if 'search' in c['class'].lower():
                    continue

                # Try clicking first icon right of search bar
                self.driver.execute_script("arguments[0].click();", c['element'])
                time.sleep(3)

                # Check if feed panel opened
                if self._check_feed_panel_opened():
                    print(f"[{self.PORTAL_NAME}] ✓ Feed panel opened!")
                    return True

            print(f"[{self.PORTAL_NAME}] ✗ Could not find My Feed button right of search bar")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error navigating to My Feed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _fallback_find_feed_button(self) -> bool:
        """Find the 'My Feed' button in the header navigation bar"""
        try:
            # Wait for React to render
            time.sleep(3)

            # MS portal uses Shadow DOM - use JS to find and click My Feed
            print(f"[{self.PORTAL_NAME}] Searching for My Feed in Shadow DOM...")
            click_success = self.driver.execute_script("""
                function findAndClickFeed(root) {
                    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
                    while (walker.nextNode()) {
                        var text = walker.currentNode.textContent.trim();
                        if (text.toLowerCase() === 'my feed') {
                            var el = walker.currentNode.parentElement;
                            var rect = el.getBoundingClientRect();
                            // Must be in header area (top 100px)
                            if (rect.top < 100) {
                                // Find clickable ancestor
                                while (el && el.tagName !== 'A' && el.tagName !== 'BUTTON' && !el.onclick && el.getAttribute('role') !== 'button') {
                                    el = el.parentElement;
                                }
                                if (el) {
                                    el.click();
                                    return true;
                                }
                            }
                        }
                    }
                    // Recursively check shadow roots
                    var allElements = root.querySelectorAll('*');
                    for (var i = 0; i < allElements.length; i++) {
                        if (allElements[i].shadowRoot && findAndClickFeed(allElements[i].shadowRoot)) {
                            return true;
                        }
                    }
                    return false;
                }
                return findAndClickFeed(document);
            """)

            if click_success:
                time.sleep(3)
                print(f"[{self.PORTAL_NAME}] ✓ Clicked My Feed")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Could not find My Feed button")
            return False

            print(f"[{self.PORTAL_NAME}] Found {len(my_feed_elements)} elements with 'My Feed' text")

            # Find the one in header (y < 100)
            target_element = None
            for el in my_feed_elements:
                try:
                    loc = el.location
                    if loc['y'] < 100 and el.is_displayed():
                        target_element = el
                        break
                except:
                    continue

            if not target_element:
                print(f"[{self.PORTAL_NAME}] ✗ No 'My Feed' element in header area")
                return False

            # Log outerHTML of the target element
            outer_html = target_element.get_attribute('outerHTML')
            print(f"[{self.PORTAL_NAME}] Target element outerHTML:")
            print(f"  {outer_html[:200]}...")

            # Step 2: Traverse ancestors and log details
            print(f"[{self.PORTAL_NAME}] Ancestor traversal:")
            current = target_element
            ancestors = []

            for depth in range(10):  # Max 10 levels up
                try:
                    parent = current.find_element(By.XPATH, '..')
                    if parent.tag_name == 'html':
                        break

                    tag = parent.tag_name
                    href = parent.get_attribute('href')
                    onclick = parent.get_attribute('onclick')
                    role = parent.get_attribute('role')
                    classes = parent.get_attribute('class') or ''

                    ancestors.append({
                        'element': parent,
                        'depth': depth,
                        'tag': tag,
                        'href': href,
                        'onclick': onclick,
                        'role': role,
                        'class': classes[:60]
                    })

                    print(f"  [{depth}] <{tag}> href={href} onclick={onclick} role={role} class='{classes[:40]}'")

                    current = parent
                except:
                    break

            # Step 3: Identify handler-owning ancestor
            # Priority: role="button" > onclick > <button> > <a> without href="#"
            click_target = None
            click_reason = ""

            for anc in ancestors:
                # Check for role="button" (React click handler likely)
                if anc['role'] == 'button':
                    click_target = anc['element']
                    click_reason = f"role=button at depth {anc['depth']}"
                    break

                # Check for onclick attribute
                if anc['onclick']:
                    click_target = anc['element']
                    click_reason = f"onclick at depth {anc['depth']}"
                    break

                # Check for button tag
                if anc['tag'] == 'button':
                    click_target = anc['element']
                    click_reason = f"<button> at depth {anc['depth']}"
                    break

                # Check for anchor without href (SPA navigation)
                if anc['tag'] == 'a':
                    if not anc['href'] or anc['href'] == '#' or 'javascript:' in (anc['href'] or ''):
                        click_target = anc['element']
                        click_reason = f"<a> without real href at depth {anc['depth']}"
                        break
                    # If anchor has real href, it might cause reload - note but continue
                    print(f"  WARNING: <a> at depth {anc['depth']} has href={anc['href']} - may cause reload")

            # If no handler found, try the first div with click-related class
            if not click_target:
                for anc in ancestors:
                    if anc['tag'] == 'div' and any(x in anc['class'].lower() for x in ['click', 'btn', 'button', 'nav', 'link']):
                        click_target = anc['element']
                        click_reason = f"<div> with click-like class at depth {anc['depth']}"
                        break

            # Fallback: use direct parent of text element
            if not click_target and ancestors:
                click_target = ancestors[0]['element']
                click_reason = "direct parent (fallback)"

            if not click_target:
                click_target = target_element
                click_reason = "text element itself (last resort)"

            print(f"[{self.PORTAL_NAME}] Click target: {click_reason}")

            # Step 4: Perform JS click on identified target
            url_before = self.driver.current_url
            print(f"[{self.PORTAL_NAME}] Clicking via JS...")
            self.driver.execute_script("arguments[0].click();", click_target)
            time.sleep(3)

            url_after = self.driver.current_url
            print(f"[{self.PORTAL_NAME}] URL after click: {url_after}")

            # Validation: Check if SPA navigation occurred (URL changed but no full reload indicator)
            if url_before != url_after:
                if 'feed' in url_after.lower() or 'myfeed' in url_after.lower():
                    print(f"[{self.PORTAL_NAME}] ✓ SPA navigation to feed page successful")
                    return True
                else:
                    print(f"[{self.PORTAL_NAME}] URL changed but not to feed page")

            # Check if page content indicates we're on feed
            page_source = self.driver.page_source.lower()
            if 'my feed' in page_source and ('followed' in page_source or 'analyst' in page_source):
                print(f"[{self.PORTAL_NAME}] ✓ Feed page content detected")
                return True

            print(f"[{self.PORTAL_NAME}] ✗ Click did not navigate to feed")
            return False

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] Error finding feed button: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _check_feed_panel_opened(self) -> bool:
        """Check if clicking an element opened a feed/notification panel"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            page_text = soup.get_text().lower()

            # Signs that a feed panel opened
            feed_indicators = ['my feed', 'recent', 'new research', 'latest', 'notifications',
                               'followed', 'updates', 'reports', 'equity research']
            return any(indicator in page_text for indicator in feed_indicators)
        except:
            return False

    # ------------------------------------------------------------------
    # Extract feed items from analyst sidebar
    # ------------------------------------------------------------------

    def _extract_notifications(self) -> List[Dict]:
        """Extract reports from My Feed page"""
        notifications = []
        seen_urls = set()

        try:
            # Wait for feed content to load
            time.sleep(2)

            # Scroll down to load more reports (3 scroll attempts)
            for scroll_idx in range(3):
                # Extract reports from current view
                new_reports = self._extract_reports_from_feed_page(seen_urls)
                notifications.extend(new_reports)

                if len(notifications) >= 20:  # Enough reports
                    break

                # Scroll down for more
                self.driver.execute_script("window.scrollBy(0, 800)")
                time.sleep(2)

            print(f"[{self.PORTAL_NAME}] ✓ Found {len(notifications)} reports in feed")
            return notifications

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] ✗ Error extracting notifications: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _extract_reports_from_feed_page(self, seen_urls: set) -> List[Dict]:
        """Extract research reports from the My Feed page using class selectors"""
        reports = []

        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Find report links by class - MS uses 'title-link search-report-title' for report titles
            report_links = soup.find_all('a', class_=lambda c: c and 'title-link' in c)

            if not report_links:
                # Fallback: find all links that look like reports
                report_links = soup.find_all('a', href=lambda h: h and ('/eqr/' in h or '/research/' in h))

            for link in report_links:
                href = link.get('href', '')

                # Skip if already seen
                if href in seen_urls:
                    continue

                # Make URL absolute
                if href.startswith('/'):
                    href = 'https://ny.matrix.ms.com' + href
                elif not href.startswith('http'):
                    continue

                seen_urls.add(href)

                # Get title
                title = link.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                # Find parent container to extract analyst and date
                parent = link.find_parent(['li', 'div', 'article'])
                analyst = None
                pub_date = None

                if parent:
                    # Look for analyst name - often in a span or link with 'analyst' class
                    analyst_el = parent.find(['a', 'span'], class_=lambda c: c and ('analyst' in c.lower() if c else False))
                    if analyst_el:
                        analyst = analyst_el.get_text(strip=True)

                    # Look for date
                    date_el = parent.find(['span', 'div'], class_=lambda c: c and ('date' in c.lower() if c else False))
                    if date_el:
                        date_text = date_el.get_text(strip=True)
                        try:
                            pub_date = dateparser.parse(date_text)
                        except:
                            pass

                    # Alternative: look for any text that looks like a date
                    if not pub_date:
                        parent_text = parent.get_text()
                        date_patterns = [
                            r'(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})',
                            r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4})',
                            r'(\d{1,2}/\d{1,2}/\d{4})',
                        ]
                        for pattern in date_patterns:
                            match = re.search(pattern, parent_text, re.I)
                            if match:
                                try:
                                    pub_date = dateparser.parse(match.group(1))
                                    break
                                except:
                                    pass

                reports.append({
                    'title': title[:200],
                    'url': href,
                    'analyst': analyst,
                    'source': 'Morgan Stanley',
                    'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
                })

            return reports

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] Error extracting from feed page: {e}")
            return []

    def _find_sidebar_analysts(self) -> List[Dict]:
        """Find analyst names/links in the left sidebar"""
        analysts = []

        try:
            # Debug: print all elements on left side of page
            print(f"[{self.PORTAL_NAME}] DEBUG: Scanning left side of page for analysts...")

            # Get all clickable/text elements
            all_elements = self.driver.find_elements(By.CSS_SELECTOR,
                'a, button, li, div[class], span[class]')

            left_side_elements = []
            for el in all_elements:
                try:
                    if el.is_displayed():
                        loc = el.location
                        size = el.size
                        # Left side of page (x < 400)
                        if loc['x'] < 400 and size['width'] > 0:
                            text = el.text.strip()
                            if text and len(text) > 3 and len(text) < 100:
                                classes = el.get_attribute('class') or ''
                                left_side_elements.append({
                                    'element': el,
                                    'tag': el.tag_name,
                                    'text': text[:60],
                                    'class': classes[:50],
                                    'x': loc['x'],
                                    'y': loc['y'],
                                    'w': size['width'],
                                    'h': size['height']
                                })
                except:
                    continue

            # Sort by y position
            left_side_elements.sort(key=lambda e: e['y'])

            # Print debug info
            print(f"[{self.PORTAL_NAME}] DEBUG: Found {len(left_side_elements)} elements on left side:")
            for i, el in enumerate(left_side_elements[:20]):
                print(f"  [{i}] <{el['tag']}> x={el['x']:.0f} y={el['y']:.0f} "
                      f"'{el['text']}' class='{el['class']}'")

            # Look for elements that look like analyst names (2+ words, proper case)
            analyst_pattern = re.compile(r'^[A-Z][a-z]+\s+[A-Z][a-z]+')

            for el_info in left_side_elements:
                text = el_info['text']
                # Check if text looks like a name (First Last format)
                if analyst_pattern.match(text):
                    # Make sure it's clickable
                    el = el_info['element']
                    if el.tag_name in ['a', 'button'] or el.get_attribute('role') == 'button':
                        analysts.append({
                            'element': el,
                            'name': text,
                            'x': el_info['x'],
                            'y': el_info['y']
                        })
                    else:
                        # Try to find clickable parent/child
                        try:
                            clickable = el.find_elements(By.CSS_SELECTOR, 'a, button')
                            if clickable:
                                analysts.append({
                                    'element': clickable[0],
                                    'name': text,
                                    'x': el_info['x'],
                                    'y': el_info['y']
                                })
                            else:
                                # Element itself might be clickable
                                analysts.append({
                                    'element': el,
                                    'name': text,
                                    'x': el_info['x'],
                                    'y': el_info['y']
                                })
                        except:
                            pass

            # Deduplicate by name
            seen_names = set()
            unique_analysts = []
            for item in analysts:
                name = item['name']
                if name not in seen_names:
                    seen_names.add(name)
                    unique_analysts.append(item)

            return unique_analysts[:10]  # Limit to first 10 analysts

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] Error finding sidebar analysts: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _extract_reports_from_current_page(self, seen_urls: set, analyst_name: str = None) -> List[Dict]:
        """Extract research reports from the current page view"""
        reports = []

        try:
            # Scroll to load content
            time.sleep(2)

            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Find all links that look like research reports
            report_patterns = [
                re.compile(r'/research/', re.I),
                re.compile(r'/report/', re.I),
                re.compile(r'/doc/', re.I),
                re.compile(r'/eqr/', re.I),
            ]

            all_links = soup.find_all('a', href=True)
            for link in all_links:
                href = link.get('href', '')

                # Check if it looks like a research report
                is_report = any(p.search(href) for p in report_patterns)
                if not is_report:
                    continue

                # Skip if already seen
                if href in seen_urls:
                    continue

                # Make URL absolute
                if href.startswith('/'):
                    href = 'https://ny.matrix.ms.com' + href
                elif not href.startswith('http'):
                    continue

                seen_urls.add(href)

                # Extract title - try multiple sources
                title = link.text.strip()

                # If link text is short, look for title in parent/siblings
                if not title or len(title) < 5:
                    title = link.get('title', '')

                if not title or len(title) < 5:
                    parent = link.find_parent(['div', 'li', 'article', 'tr', 'td'])
                    if parent:
                        parent_text = parent.get_text(separator=' ', strip=True)
                        if len(parent_text) > len(title):
                            title = parent_text[:200]

                if not title or len(title) < 5:
                    parent = link.find_parent(['div', 'li', 'article'])
                    if parent:
                        heading = parent.find(['h1', 'h2', 'h3', 'h4', 'strong', 'b'])
                        if heading:
                            title = heading.get_text(strip=True)

                if not title or len(title) < 5:
                    title = 'Untitled'

                # Try to find analyst and date from surrounding context
                parent = link.find_parent(['div', 'li', 'article', 'tr'])
                extracted_analyst = self._extract_analyst_from_element(parent)
                pub_date = self._extract_date_from_element(parent)

                # Use provided analyst name if we couldn't extract one
                final_analyst = extracted_analyst or analyst_name

                reports.append({
                    'title': title[:200],
                    'url': href,
                    'analyst': final_analyst,
                    'source': 'Morgan Stanley',
                    'date': pub_date.strftime('%Y-%m-%d') if pub_date else None,
                })

            return reports

        except Exception as e:
            print(f"[{self.PORTAL_NAME}] Error extracting from page: {e}")
            return []

    def _extract_analyst_from_element(self, element) -> Optional[str]:
        """Try to extract analyst name from element"""
        if not element:
            return None

        text = element.text if element else ''
        # Common patterns: "by Analyst Name" or "Analyst Name - Topic"
        patterns = [
            r'by\s+([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[-–]\s*\w+',
            r'Author:\s*([A-Z][a-z]+\s+[A-Z][a-z]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _extract_date_from_element(self, element) -> Optional[datetime]:
        """Try to extract date from element"""
        if not element:
            return None

        text = element.text if element else ''
        try:
            # Look for various date formats
            patterns = [
                r'(\d{1,2}/\d{1,2}/\d{4})',
                r'(\d{1,2}-\d{1,2}-\d{4})',
                r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})',
                r'(\d{4}-\d{2}-\d{2})',
            ]
            for pattern in patterns:
                match = re.search(pattern, text, re.I)
                if match:
                    return dateparser.parse(match.group(1))
        except:
            pass
        return None

    # ------------------------------------------------------------------
    # Navigate to report and extract content
    # ------------------------------------------------------------------

    def _navigate_to_report(self, report_url: str) -> bool:
        """Navigate to a specific report page"""
        try:
            self.driver.get(report_url)
            time.sleep(4)
            return True
        except Exception as e:
            print(f"    ✗ Error navigating to report: {e}")
            return False

    def _extract_report_content(self, report: Dict = None) -> Optional[str]:
        """Extract content from report page - scroll to reveal PDF button"""

        # First, scroll down to reveal the PDF button
        self.driver.execute_script("window.scrollBy(0, 200)")
        time.sleep(2)

        # Look for PDF button (document icon in top right)
        pdf_url = self._get_pdf_url()
        if pdf_url:
            self._sync_cookies_from_driver()
            pdf_bytes = self.download_pdf(pdf_url)
            if pdf_bytes:
                # Save PDF
                if report:
                    pdf_path = self._save_pdf(pdf_bytes, report)
                    if pdf_path:
                        report['pdf_path'] = pdf_path

                text = self.extract_text_from_pdf(pdf_bytes)
                if text:
                    return text

        # Fallback: try to extract text directly from page
        text = self._extract_text_from_page()
        if text and len(text) > 500:
            return text

        return None

    def _get_pdf_url(self) -> Optional[str]:
        """Find and click PDF button, get PDF URL"""
        try:
            # Look for PDF/document button
            pdf_selectors = [
                '[aria-label*="PDF"]',
                '[aria-label*="pdf"]',
                '[aria-label*="Download"]',
                '[title*="PDF"]',
                '[title*="pdf"]',
                '[title*="Document"]',
                'button[class*="pdf"]',
                'a[class*="pdf"]',
                '.pdf-button',
                '.download-pdf',
                # Icon-based
                '[class*="document"]',
                '[class*="file"]',
                'svg[class*="pdf"]',
            ]

            for selector in pdf_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for el in elements:
                        if el.is_displayed():
                            # Check if it's related to PDF
                            text = (el.text or '').lower()
                            aria = (el.get_attribute('aria-label') or '').lower()
                            title = (el.get_attribute('title') or '').lower()
                            classes = (el.get_attribute('class') or '').lower()

                            if any(x in text + aria + title + classes for x in ['pdf', 'document', 'download']):
                                # Click to potentially reveal PDF link or trigger download
                                self.driver.execute_script("arguments[0].click();", el)
                                time.sleep(2)
                                break
                except:
                    continue

            # Check for PDF URLs in page source after clicking
            page_source = self.driver.page_source
            pdf_patterns = [
                r'(https?://[^\s"\']*\.pdf[^\s"\']*)',
                r'(https?://[^\s"\']*download[^\s"\']*pdf[^\s"\']*)',
                r'(https?://[^\s"\']*\/doc\/[^\s"\']*)',
            ]

            for pattern in pdf_patterns:
                matches = re.findall(pattern, page_source, re.I)
                for url in matches:
                    if '.pdf' in url.lower() or '/doc/' in url.lower():
                        print(f"    ✓ Found PDF URL: {url[:60]}...")
                        return url

            # Check iframes
            iframes = self.driver.find_elements(By.TAG_NAME, 'iframe')
            for iframe in iframes:
                src = iframe.get_attribute('src') or ''
                if '.pdf' in src.lower() or '/doc/' in src.lower():
                    print(f"    ✓ Found PDF in iframe: {src[:60]}...")
                    return src

            return None

        except Exception as e:
            print(f"    ⚠ Error getting PDF URL: {e}")
            return None

    def _extract_text_from_page(self) -> Optional[str]:
        """Try to extract report text directly from the page"""
        try:
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')

            # Remove non-content elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer']):
                element.decompose()

            # Look for main content
            content_selectors = [
                '.report-content',
                '.document-content',
                '.article-content',
                '.research-content',
                'article',
                'main',
                '[role="main"]',
            ]

            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    text = content.get_text(separator='\n', strip=True)
                    if len(text) > 500:
                        return text

            return None

        except Exception as e:
            print(f"    ⚠ Error extracting page text: {e}")
            return None


# ------------------------------------------------------------------
# Entry point for testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("\nMorgan Stanley Scraper Test")
    print("=" * 50)

    # Check for credentials
    email = os.getenv('MS_EMAIL')
    password = os.getenv('MS_PASSWORD')

    if not email or not password:
        print("✗ Missing MS_EMAIL or MS_PASSWORD in .env file")
        print("  Add these lines to your .env file:")
        print("    MS_EMAIL=your_email@example.com")
        print("    MS_PASSWORD=your_password")
        sys.exit(1)

    print(f"✓ Found credentials for: {email}")

    # Test scraper
    print("\n[1/2] Initializing scraper (non-headless for testing)...")
    scraper = MorganStanleyScraper(headless=False)

    print("\n[2/2] Testing full pipeline...")
    result = scraper.get_followed_reports(max_reports=5, days=5)

    # Check result
    if result.get('auth_required'):
        print("\n⚠ Authentication required - check credentials")
        sys.exit(1)

    reports = result.get('reports', [])
    failures = result.get('failures', [])

    print(f"\n--- Results ---")
    print(f"Reports extracted: {len(reports)}")
    print(f"Failures: {len(failures)}")

    for i, report in enumerate(reports[:3], 1):
        print(f"\n  Report {i}:")
        print(f"    Title: {report['title'][:60]}...")
        print(f"    Analyst: {report.get('analyst', 'unknown')}")
        print(f"    Date: {report.get('date', 'unknown')}")

    if failures:
        print(f"\n--- Failures ---")
        for f in failures[:5]:
            print(f"  - {f}")

    print("\n✓ Morgan Stanley scraper test complete")
