async (page) => {
  const results = await page.evaluate(() => window.__issUnetMatrixResults || null);
  throw new Error(JSON.stringify(results, null, 2));
}
