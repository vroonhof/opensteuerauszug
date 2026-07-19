/*
 * Mock Pyodide runtime for testing the web app UI without downloading the
 * real (~40 MB) WebAssembly runtime.
 *
 * Implements just enough of the Pyodide API surface used by the worker in
 * web/app_template.html: loadPyodide, FS, loadPackage, pyimport("micropip"),
 * globals and runPython/runPythonAsync.  The "pipeline run" verifies that
 * the expected files were written into the virtual filesystem and produces
 * dummy PDF/XML outputs, so an end-to-end browser test can drive the whole
 * wizard.  Used by web/dev/e2e_smoke.mjs.
 */
"use strict";

function makeFS() {
  const files = new Map(); // path -> Uint8Array
  const dirs = new Set(["/"]);
  const DIR_MODE = 0x4000;
  const FILE_MODE = 0x8000;
  const parent = (p) => p.slice(0, p.lastIndexOf("/")) || "/";
  return {
    mkdirTree(path) {
      const parts = path.split("/").filter(Boolean);
      let cur = "";
      for (const part of parts) {
        cur += "/" + part;
        dirs.add(cur);
      }
    },
    writeFile(path, data) {
      this.mkdirTree(parent(path));
      files.set(path, typeof data === "string" ? new TextEncoder().encode(data) : data);
    },
    readFile(path) {
      if (!files.has(path)) throw new Error("mock FS: no such file " + path);
      return files.get(path);
    },
    readdir(path) {
      const names = new Set([".", ".."]);
      const prefix = path === "/" ? "/" : path + "/";
      for (const p of [...files.keys(), ...dirs]) {
        if (p !== path && p.startsWith(prefix)) {
          names.add(p.slice(prefix.length).split("/")[0]);
        }
      }
      return [...names];
    },
    stat(path) {
      if (dirs.has(path)) return { mode: DIR_MODE };
      if (files.has(path)) return { mode: FILE_MODE };
      throw new Error("mock FS: no such path " + path);
    },
    isDir(mode) { return mode === DIR_MODE; },
    unlink(path) { files.delete(path); },
    rmdir(path) { dirs.delete(path); },
    _files: files,
  };
}

function loadPyodide(_opts) {
  const FS = makeFS();
  const globals = new Map();
  const pyodide = {
    FS,
    globals: { set: (k, v) => globals.set(k, v), get: (k) => globals.get(k) },
    async loadPackage(_names, _opts2) {},
    pyimport(name) {
      if (name === "micropip") {
        return { install: { async callKwargs(_reqs, _kw) {} } };
      }
      throw new Error("mock pyimport: " + name);
    },
    runPython(code) {
      if (code.includes("ensure_workspace")) {
        for (const d of ["input", "kursliste", "output", "config"]) FS.mkdirTree("/work/" + d);
        globals.set("_version", "0.0-mock");
      }
    },
    async runPythonAsync(code) {
      if (code.includes("convert_kursliste_xmls")) {
        // Emulate the streaming XML -> SQLite conversion: replace each XML in
        // /work/kursliste with a mock kursliste_<year>.sqlite.
        const log = globals.get("_log_cb");
        const result = { converted: [], skipped: [], errors: [] };
        for (const name of FS.readdir("/work/kursliste")) {
          if (!/\.xml$/i.test(name)) continue;
          const year = (name.match(/(\d{4})/) || [])[1] || "0000";
          const dbPath = "/work/kursliste/kursliste_" + year + ".sqlite";
          FS.writeFile(dbPath, "SQLite mock (from " + name + ")");
          FS.unlink("/work/kursliste/" + name);
          log("MOCK converted " + name + " -> kursliste_" + year + ".sqlite");
          result.converted.push({ source: name, path: dbPath, year: Number(year),
                                  size: FS.readFile(dbPath).length });
        }
        return JSON.stringify(result);
      }
      if (!code.includes("run_process")) throw new Error("mock: unexpected python\n" + code);
      const params = JSON.parse(globals.get("_params_json"));
      const log = globals.get("_log_cb");
      log("MOCK pipeline starting");
      log("MOCK importer=" + params.importer + " tax_year=" + params.tax_year);
      const inputs = FS.readdir("/work/input").filter((n) => n !== "." && n !== "..");
      const kursliste = FS.readdir(params.kursliste_dir).filter((n) => n !== "." && n !== "..");
      log("MOCK inputs: " + inputs.join(", "));
      log("MOCK kursliste: " + kursliste.join(", "));
      log("MOCK config:\n" + new TextDecoder().decode(FS.readFile(params.config_path)));
      const outputs = {};
      let exitCode = 0;
      if (!inputs.length || !kursliste.length) {
        log("MOCK error: missing input or kursliste files");
        exitCode = 1;
      } else {
        FS.writeFile(params.output_pdf, "%PDF-1.4 mock steuerauszug\n%%EOF");
        FS.writeFile(params.xml_output, "<taxStatement mock='true'/>");
        outputs.pdf = params.output_pdf;
        outputs.xml = params.xml_output;
        log("Processing finished successfully.");
      }
      return JSON.stringify({
        exit_code: exitCode,
        success: exitCode === 0,
        outputs,
      });
    },
  };
  return Promise.resolve(pyodide);
}

// importScripts() target: expose the entry point like the real pyodide.js.
self.loadPyodide = loadPyodide;
