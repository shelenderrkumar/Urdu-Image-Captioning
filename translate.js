const xlsx = require('xlsx');
const puppeteer = require('puppeteer');
const fs = require('fs');

async function translateText(page, text) {
    console.log(`Translating: ${text}`);
    const translationUrl = `https://translate.google.com/?sl=en&tl=ur&text=${encodeURIComponent(text)}&op=translate`;
    await page.goto(translationUrl);
    
    // Adjust the selector as per the Google Translate's output field
    const selector = 'span[jsname="W297wb"]';
    await page.waitForSelector(selector);
    const translatedText = await page.$eval(selector, element => element.innerText);

    return translatedText;
}

async function processExcelFile(filePath) {
    console.log(`Processing file: ${filePath}`);
    const workbook = xlsx.readFile(filePath);
    console.log(`workbook got`);
    const sheetName = workbook.SheetNames[0];
    console.log(`Sheet Name: ${sheetName}`);
    const sheet = workbook.Sheets[sheetName];
    const data = xlsx.utils.sheet_to_json(sheet);
    console.log(`Started reading columns:`);

    const browser = await puppeteer.launch({ headless: false });
    const page = await browser.newPage();

    const outputStream = fs.createWriteStream('translatedTexts.txt', { flags: 'a' });

    for (const row of data) {
        if (row.comment) { // Replace 'Captions' with the actual header name of column C
            const translated = await translateText(page, row.comment);
            console.log(`Translated: ${translated}`);
            outputStream.write(`${translated}\n`);
        }
    }

    outputStream.close();
    await browser.close();
}

/*
async function main() {
    const translated1 = await translateText("Stock price of Adani has grown by 18 percent.");
    console.log(translated1);
}

main();
*/

processExcelFile("C:\\Users\\Shelender Kumar\\Downloads\\results.xlsx");

