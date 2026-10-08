from playwright.sync_api import sync_playwright


class BrowserManager:
    """
    Manages the Playwright browser, context and page.
    """

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def start(self):
        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.launch(
            headless=self.headless
        )

        self.context = self.browser.new_context(
            viewport={
                "width": 1440,
                "height": 900
            },
            accept_downloads=True
        )

        self.page = self.context.new_page()

        return self.page

    def close(self):
        try:
            if self.context:
                self.context.close()
        finally:
            if self.browser:
                self.browser.close()

            if self.playwright:
                self.playwright.stop()