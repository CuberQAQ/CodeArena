import { Page } from "@playwright/test";

const SCREENSHOTS_DIR = "e2e/integration/screenshots";

export async function screenshotPage(page: Page, name: string): Promise<void> {
  await page.screenshot({
    path: `${SCREENSHOTS_DIR}/${name}.png`,
    fullPage: true,
  });
}
