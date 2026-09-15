const { chromium } = require("playwright");
const path = require("node:path");
const readline = require("node:readline/promises");
const { stdin, stdout } = require("node:process");

const PROFILE_DIR = path.resolve("dm-browserprofil");
const AUTH_STATE_PATH = path.resolve("dm-auth.json");

async function main() {
  const context = await chromium.launchPersistentContext(PROFILE_DIR, {
    channel: "chrome",
    headless: false,
    viewport: null,
    acceptDownloads: true,
  });

  const pages = context.pages();
  const page = pages[0] ?? (await context.newPage());

  await page.goto("https://www.dm.de/services/dm-konto", {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });

  console.log("");
  console.log("1. Klicke im Browser auf „Melde Dich in Deinem dm-Konto an“.");
  console.log("2. Melde dich vollständig an.");
  console.log("3. Öffne anschließend „Meine Einkäufe“.");
  console.log("4. Kehre danach zu diesem Terminal zurück.");
  console.log("");

  const terminal = readline.createInterface({ input: stdin, output: stdout });

  await terminal.question(
    "Drücke erst Enter, wenn „Meine Einkäufe“ sichtbar ist: "
  );

  await context.storageState({ path: AUTH_STATE_PATH });

  console.log(`Aktuelle URL: ${page.url()}`);
  console.log(`Das Profil wurde gespeichert unter: ${PROFILE_DIR}`);
  console.log(`Die Session wurde gespeichert unter: ${AUTH_STATE_PATH}`);
  console.log(
    "Weiter geht's mit: npx playwright test dm-download.spec.js"
  );

  terminal.close();
  await context.close();
}

main().catch((error) => {
  console.error("Fehler:", error.message);
  process.exitCode = 1;
});
