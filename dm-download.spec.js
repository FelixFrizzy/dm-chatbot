import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

test.use({
  storageState: "dm-auth.json",
  acceptDownloads: true,
});

test.setTimeout(60 * 60 * 1000);

const DOWNLOAD_DIR = path.resolve("downloads");
const DEBUG_DIR = path.resolve("debug");

function cleanFilename(value) {
  return value
    .replace(/[<>:"/\\|?*\u0000-\u001F]/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 180);
}

async function fileExists(filename) {
  try {
    await fs.access(filename);
    return true;
  } catch {
    return false;
  }
}

function getPurchaseLinks(page) {
  return page
    .locator("main")
    .getByRole("link", {
      name: /(?:Im Markt eingekauft|Bei Dir angekommen|Wurde von Dir abgeholt|Bestellung|Am \d{2}\.\d{2}\.)/i,
    });
}

async function loadAllPurchases(page) {
  let rounds = 0;
  let unsuccessfulRounds = 0;

  while (rounds < 100) {
    const purchases = getPurchaseLinks(page);
    const before = await purchases.count();

    const loadMore = page
      .locator("button:visible, a:visible")
      .filter({
        hasText: /mehr laden|weitere einkäufe|mehr anzeigen|weitere anzeigen/i,
      })
      .last();

    if ((await loadMore.count()) === 0) {
      console.log("Kein weiterer „Mehr laden“-Button gefunden.");
      break;
    }

    console.log(`Klicke „Mehr laden“ bei ${before} Einkäufen ...`);

    try {
      await loadMore.scrollIntoViewIfNeeded();
      await loadMore.click({
        timeout: 15_000,
      });
    } catch (error) {
      console.log(`„Mehr laden“ konnte nicht angeklickt werden: ${error.message}`);
      break;
    }

    try {
      await expect
        .poll(async () => getPurchaseLinks(page).count(), {
          timeout: 15_000,
          intervals: [250, 500, 1000],
        })
        .toBeGreaterThan(before);
    } catch {
      // Die abschließende Prüfung erfolgt nach einer zusätzlichen Pause.
    }

    await page.waitForTimeout(1000);

    const after = await getPurchaseLinks(page).count();

    console.log(`Einkäufe: ${before} → ${after}`);

    if (after <= before) {
      unsuccessfulRounds += 1;

      if (unsuccessfulRounds >= 2) {
        console.log(
          "„Mehr laden“ hat zweimal keine neuen Einkäufe geladen."
        );
        break;
      }
    } else {
      unsuccessfulRounds = 0;
    }

    rounds += 1;
  }

  return getPurchaseLinks(page).count();
}

async function openPurchasesPage(page) {
  await page.goto("https://www.dm.de/", {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });

  const cookieButton = page.getByRole("button", {
    name: /alle akzeptieren|akzeptieren|zustimmen/i,
  });

  if (await cookieButton.first().isVisible().catch(() => false)) {
    await cookieButton.first().click();
  }

  const mainNavigationButton = page
    .getByRole("navigation", { name: "Haupt" })
    .getByRole("button");

  await mainNavigationButton.click();

  await page
    .getByRole("link", {
      name: "Meine Einkäufe",
    })
    .click();

  await expect(getPurchaseLinks(page).first()).toBeVisible({
    timeout: 20_000,
  });

  return page.url();
}

async function returnToPurchaseList(page, purchasesUrl) {
  try {
    await page.goBack({
      waitUntil: "domcontentloaded",
      timeout: 30_000,
    });
  } catch {
    // Falls Zurück nicht funktioniert, wird die Übersichtsseite direkt geöffnet.
  }

  const firstPurchaseVisible = await getPurchaseLinks(page)
    .first()
    .isVisible()
    .catch(() => false);

  if (!firstPurchaseVisible) {
    await page.goto(purchasesUrl, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
  }

  await expect(getPurchaseLinks(page).first()).toBeVisible({
    timeout: 20_000,
  });

  /*
   * dm kann die Liste nach dem Zurückgehen wieder einklappen.
   * Deshalb werden alle Einkäufe erneut geladen.
   */
  await loadAllPurchases(page);
}

async function findDocumentControl(page) {
  const documentName =
    /Rechnung anzeigen|Rechnung herunterladen|Kassenbon anzeigen|Kassenbon herunterladen|Bon anzeigen|Bon herunterladen|eBon anzeigen|eBon herunterladen|PDF anzeigen|PDF herunterladen/i;

  const button = page
    .getByRole("button", {
      name: documentName,
    })
    .first();

  if (await button.isVisible().catch(() => false)) {
    return button;
  }

  const link = page
    .getByRole("link", {
      name: documentName,
    })
    .first();

  if (await link.isVisible().catch(() => false)) {
    return link;
  }

  /*
   * Ersatzsuche, falls der zugängliche Name von dm anders gesetzt wird.
   */
  const fallback = page
    .locator("button:visible, a:visible")
    .filter({
      hasText:
        /rechnung|kassenbon|e-?bon|pdf herunterladen|pdf anzeigen/i,
    })
    .first();

  if (await fallback.isVisible().catch(() => false)) {
    return fallback;
  }

  return null;
}

async function saveDebugInformation(page, index, label) {
  const baseName = cleanFilename(
    `${String(index + 1).padStart(4, "0")}_${label}`
  );

  const screenshotPath = path.join(
    DEBUG_DIR,
    `${baseName}.png`
  );

  const htmlPath = path.join(
    DEBUG_DIR,
    `${baseName}.html`
  );

  await page.screenshot({
    path: screenshotPath,
    fullPage: true,
  });

  await fs.writeFile(
    htmlPath,
    await page.content(),
    "utf8"
  );

  const visibleControls = await page
    .locator("button:visible, a:visible")
    .allTextContents()
    .catch(() => []);

  console.log("  Keine Rechnung und kein Kassenbon gefunden.");
  console.log(`  URL: ${page.url()}`);
  console.log(
    `  Sichtbare Bedienelemente: ${visibleControls
      .map((text) => text.replace(/\s+/g, " ").trim())
      .filter(Boolean)
      .join(" | ")}`
  );
  console.log(`  Screenshot: ${screenshotPath}`);
  console.log(`  HTML:       ${htmlPath}`);
}

test("alle dm-Rechnungen und Kassenbons herunterladen", async ({ page }) => {
  await fs.mkdir(DOWNLOAD_DIR, {
    recursive: true,
  });

  await fs.mkdir(DEBUG_DIR, {
    recursive: true,
  });

  console.log("Öffne „Meine Einkäufe“ ...");

  const purchasesUrl = await openPurchasesPage(page);
  const totalPurchases = await loadAllPurchases(page);

  console.log("");
  console.log(`${totalPurchases} Einkäufe insgesamt gefunden.`);
  console.log("");

  let downloaded = 0;
  let skipped = 0;
  let failed = 0;

  for (let index = 0; index < totalPurchases; index += 1) {
    /*
     * Der Locator wird nach jedem Zurückkehren neu erzeugt,
     * da dm die Einkaufsliste dynamisch aufbaut.
     */
    const purchases = getPurchaseLinks(page);
    const currentCount = await purchases.count();

    if (index >= currentCount) {
      console.error(
        `[${index + 1}/${totalPurchases}] Einkauf nicht mehr gefunden.`
      );

      failed += 1;
      continue;
    }

    const purchase = purchases.nth(index);
    const rawLabel = await purchase.innerText();
    const label = cleanFilename(rawLabel);

    const documentType = /Im Markt eingekauft/i.test(label)
      ? "Kassenbon"
      : "Rechnung";

    console.log(
      `[${index + 1}/${totalPurchases}] ${label}`
    );

    try {
      await purchase.scrollIntoViewIfNeeded();

      await purchase.click({
        timeout: 20_000,
      });

      /*
       * Kurz warten, damit dm die Detailansicht vollständig aufbauen kann.
       */
      await page.waitForTimeout(800);

      let documentControl = await findDocumentControl(page);

      /*
       * Falls der Button verzögert erscheint, einige Sekunden erneut suchen.
       */
      if (!documentControl) {
        for (let attempt = 0; attempt < 10; attempt += 1) {
          await page.waitForTimeout(500);
          documentControl = await findDocumentControl(page);

          if (documentControl) {
            break;
          }
        }
      }

      if (!documentControl) {
        await saveDebugInformation(
          page,
          index,
          label
        );

        skipped += 1;

        await returnToPurchaseList(
          page,
          purchasesUrl
        );

        continue;
      }

      /*
       * Das Download-Ereignis muss vor dem Klick registriert werden.
       */
      const downloadPromise = page.waitForEvent("download", {
        timeout: 30_000,
      });

      await documentControl.click();

      const download = await downloadPromise;

      const suggestedFilename = download.suggestedFilename();
      const suggestedExtension = path.extname(suggestedFilename);
      const extension = suggestedExtension || ".pdf";

      const filename = cleanFilename(
        `${String(index + 1).padStart(4, "0")}_${documentType}_${label}${extension}`
      );

      const destination = path.join(
        DOWNLOAD_DIR,
        filename
      );

      if (await fileExists(destination)) {
        console.log(`  Bereits vorhanden: ${filename}`);
        skipped += 1;
      } else {
        await download.saveAs(destination);

        console.log(`  Gespeichert: ${filename}`);
        downloaded += 1;
      }
    } catch (error) {
      console.error(`  Fehler: ${error.message}`);
      failed += 1;
    }

    if (index < totalPurchases - 1) {
      await returnToPurchaseList(
        page,
        purchasesUrl
      );
    }
  }

  console.log("");
  console.log("Fertig:");
  console.log(`Heruntergeladen: ${downloaded}`);
  console.log(`Übersprungen:    ${skipped}`);
  console.log(`Fehlgeschlagen:  ${failed}`);
  console.log(`Dokumente:       ${DOWNLOAD_DIR}`);
  console.log(`Fehlerdiagnose:  ${DEBUG_DIR}`);
});
