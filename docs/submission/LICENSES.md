# Third-party notices

Relay's original code is covered by the [root MIT license](../../LICENSE). The Even Hub starter's [original MIT notice](../../frontend/LICENSE) remains in place. The built WebView carries notices for Relay, the starter, and `@evenrealities/even_hub_sdk` 0.0.10. The latter comes verbatim from the locked installed SDK.

| Dependency scope | Review |
| --- | --- |
| Browser bundle | The Even Hub SDK is the sole npm runtime dependency. Keep the [SDK notice](../../frontend/public/EVEN-HUB-SDK-LICENSE.txt) with the bundle. The [starter](../../frontend/public/EVEN-HUB-STARTER-LICENSE.txt) and [Relay](../../frontend/public/RELAY-LICENSE.txt) notices also ship. |
| Frontend tooling | TypeScript, Vite, simulator, and CLI are installed via the lockfile for development. The CLI package metadata has no license field. Review upstream distribution terms separately before redistributing CLI or simulator binaries. They are outside the release payload. |
| Python environment | The locked packages install separately from source. Installed metadata includes MIT, BSD, Apache-2.0, PSF-2.0, and certifi under MPL-2.0. No Python dependencies or certificate bundle ship in the web package. Preserve each dependency's notices and review redistribution obligations if distributing a bundled backend. |
| External services | Notion and Gemini are accessed through their APIs under their respective terms. The release contains no service credentials or vendor datasets. |

The review covers the source repository and web package. It found no identified conflict with MIT licensing Relay's own code. Official SDK and starter rights remain with their respective holders. The project logo is a Relay asset. Screenshots depict Relay running on the official simulator.
