BoodschappenWijzer — software notices

Application code: MIT; third-party components retain their own licences.
Price-source data is not relicensed by the application licence. The separately
served store-location database is attributed to OpenStreetMap contributors and
licensed under ODbL: https://www.openstreetmap.org/copyright

The browser uses unmodified Pyodide 314.0.7 runtime assets from its npm package.
Corresponding source (including build instructions and patches):
https://github.com/pyodide/pyodide/tree/314.0.7
Source archive: https://github.com/pyodide/pyodide/archive/refs/tags/314.0.7.tar.gz
Pyodide's MPL licence does not replace the licences of CPython and its native
runtime components. This runtime identifies CPython 3.14.2 and Emscripten 5.0.3.
Their source trees are available at:
https://github.com/python/cpython/tree/v3.14.2
https://github.com/emscripten-core/emscripten/tree/5.0.3

Source rebuilding instructions and upstream modification summary are in
public-site/licenses/runtime-source.txt in the source release. Use the pinned recursive Git
checkout; a source archive alone does not contain the build submodule.
Pyodide also vendors stackframe/error-stack-parser; its MIT notice is included.

RUNTIME NOTICE REVIEW: COMPLETE FOR THE PINNED ARTIFACTS
The component review and generated-output check are recorded in
public-site/licenses/native-runtime-audit.txt in the source release. Any runtime/dependency
change requires review again. This does not establish overall publication
readiness, price-data permission or bit-for-bit upstream build reproducibility.
A successful asset build verifies integrity against the reviewed inventory.

Additional pinned native source provenance (from Pyodide cpython/Makefile):
https://github.com/pyodide/pyodide/blob/314.0.7/cpython/Makefile
libffi: https://github.com/libffi/libffi/tree/f08493d249d2067c8b3207ba46693dd858f95db3
hiwire (MPL-2.0 source): https://github.com/pyodide/hiwire/tree/6a1e67280a15d929ebeceee54a6358c9c8d5f697
liblzma: https://github.com/tukaani-project/xz/tree/v5.2.2
Zstandard: https://github.com/python/cpython-source-deps/tree/zstd-1.5.7
SQLite: https://www.sqlite.org/2022/sqlite-autoconf-3390000.tar.gz
Emscripten's bzip2 port: https://github.com/emscripten-ports/bzip2/tree/1.0.6

Included notices
- Pyodide and hiwire MPL, CPython licence and incorporated-software notices.
- Emscripten, musl, compiler-rt, libc++, libc++abi, libunwind and llvm-libc.
- zlib, Expat, libffi, Zstandard, XZ/liblzma, bzip2 and SQLite.
- MiniLZ4, mpdecimal and dlmalloc source declarations.
- Tomli MIT text and Unicode License V3, with Unicode 16.0.0 data README.
  Tomli tag 2.2.1 supplies the licence text; no bundled Tomli version is inferred.
- Additional Emscripten runtime/compiler source comments and contributor credits.
  Optional/platform headers are included conservatively; see the audit checklist.
- Additional CPython core/module source notices: 832 files, 72 comments.
- Additional libffi shared/header/wasm32 source notices from 14 files.
- Source notices for zlib (27 files), Expat (19), bzip2 (15), Zstandard (90)
  and XZ liblzma/common (157); Zstandard uses the offered BSD option.
- Additional mpdecimal source notices: 33 C/header files, two distinct comments.
- Additional musl source notices: 125 C/header files, 52 distinct comments.
- HACL source notices: all 47 C/header files reviewed, three distinct comments.
- JavaScript package notices selected from actual bundler inputs, including
  separate pako zlib source headers.

Optional-component notices are included conservatively. Inclusion does not claim
that every listed source file or platform variant is linked into this binary.
Exact URLs, hashes and extraction rules are recorded in provenance.json.
The SQLite declaration and HACL source comparison are already collected; they
are not outstanding extraction tasks.

runtime-assets.json pins sizes and SHA-256 for the five runtime assets served.
The build checks both installed inputs and copied distribution files against it.
No application modifications are made to those precompiled runtime assets.
Upstream build instructions and patches remain at the source links above.
