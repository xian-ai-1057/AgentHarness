import { cpSync, createReadStream, existsSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * KaTeX 的 CSS 每種字型都列了 woff2、woff、ttf 三種檔案，Vite 會全部
 * 複製出來（約 800KB、40 個檔案）。支援的瀏覽器都讀 woff2，所以在 Vite
 * 處理 url() 之前把 woff 與 ttf 的項目拿掉。
 */
function katexWoff2Only(): Plugin {
  return {
    name: "katex-woff2-only",
    enforce: "pre",
    transform(code, id) {
      const file = id.split("?")[0] ?? id;
      if (!/[\\/]katex(\.min)?\.css$/.test(file)) return null;
      return {
        code: code.replace(
          /,\s*url\([^)]*\.(?:woff|ttf)\)\s*format\(["'](?:woff|truetype)["']\)/g,
          "",
        ),
        map: null,
      };
    },
  };
}

/**
 * PDF.js 顯示中文 PDF 需要的字元對照表（cmaps）與標準字型
 * （standard_fonts），讀 PDF 時才用網址載入（見 PdfViewer.tsx 的
 * PDFJS_ASSETS）。打包時複製到 pdfjs/ 底下，開發時直接從 node_modules 送出。
 */
function pdfjsAssets(): Plugin {
  const root = dirname(
    createRequire(import.meta.url).resolve("pdfjs-dist/package.json"),
  );
  const folders = ["cmaps", "standard_fonts"];
  let outDir = "";
  return {
    name: "pdfjs-assets",
    configResolved(config) {
      outDir = config.build.outDir;
    },
    configureServer(server) {
      server.middlewares.use("/pdfjs/", (request, response, next) => {
        const path = normalize(decodeURIComponent(request.url ?? "/"))
          .replace(/^[/\\]+/, "")
          .split("?")[0];
        const file = path ? join(root, path) : "";
        if (
          !file ||
          !folders.some((folder) => path?.startsWith(`${folder}/`)) ||
          !existsSync(file) ||
          !statSync(file).isFile()
        ) {
          next();
          return;
        }
        createReadStream(file).pipe(response);
      });
    },
    closeBundle() {
      for (const folder of folders) {
        cpSync(join(root, folder), join(outDir, "pdfjs", folder), {
          recursive: true,
        });
      }
    },
  };
}

// 開發時：先在專案資料夾執行 `harness web`，再執行 `npm run dev:web`，
// Vite 會把 /api 轉給 harness web（預設 4321 埠）。
export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  plugins: [katexWoff2Only(), pdfjsAssets(), react()],
  build: {
    outDir: fileURLToPath(new URL("../dist/public", import.meta.url)),
    emptyOutDir: true,
    // 打包進前端的第三方套件授權（MIT、BSD 等要求散布時附上授權條文），
    // 輸出成 THIRD_PARTY_LICENSES.md，隨打包結果一起散布。
    license: { fileName: "THIRD_PARTY_LICENSES.md" },
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.HARNESS_WEB_URL ?? "http://127.0.0.1:4321",
        changeOrigin: true,
      },
    },
  },
});
