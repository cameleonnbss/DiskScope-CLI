# DiskTop

_[🇬🇧 Read this in English](README.md)_

*(anciennement « DiskScope CLI » — même moteur, nouveau logo ; le dépôt, les
modules et le chemin du cache gardent l'ancien nom pour ne rien casser.)*

[![CI](https://github.com/cameleonnbss/DiskScope-CLI/actions/workflows/ci.yml/badge.svg)](https://github.com/cameleonnbss/DiskScope-CLI/actions/workflows/ci.yml)
[![Télécharger](https://img.shields.io/badge/T%C3%A9l%C3%A9charger-DiskTop.exe-brightgreen)](https://github.com/cameleonnbss/DiskScope-CLI/releases/latest)

**Analyseur de stockage Windows — 100 % en ligne de commande, données réelles uniquement.**
Analysez vos disques, trouvez ce qui mange votre espace **et ce qui mange votre RAM**, repérez les fichiers anciens, détectez les jeux Steam / Epic / Battle.net / EA / Ubisoft / Riot / GOG et passez en revue une liste de nettoyage sous double validation.

Tout ce qui s'affiche est calculé à partir de votre disque réel **et de la mémoire vive en direct** : tailles, dates, jeux, applications, processus. Aucune donnée fausse, aucune progression simulée.

---

## Fonctionnalités

| Menu | Rôle |
|---|---|
| **1 — Analyse complète** | Scan parallèle de tous les disques fixes : tailles, nombres de fichiers, gros/anciens fichiers, top dossiers par disque, exploration interactive |
| **2 — Analyse rapide** | Vue d'ensemble des disques + tailles des dossiers de premier niveau de C:, **en parallèle** (pool de threads) |
| **3 — Applications** | Clés de désinstallation du registre + programmes AppData + applis du Store, tailles réelles mesurées, estimations honnêtement signalées |
| **4 — Jeux** | Steam (manifestes `.acf`), Epic (`.item`), Battle.net, Ubisoft Connect, EA App, Riot, GOG, Xbox — preuves locales réelles seulement |
| **5 — Gros fichiers** | Fichiers les plus volumineux avec seuil réglable (>1 Go…>9 Go, ou >100 Mo) |
| **6 — Fichiers anciens** | Paliers 30 j / 90 j / 180 j / 1 an / 2 ans + répartition par catégorie (archives, ISO, installateurs, vidéos, logs, temp, builds) |
| **D — Doublons** | Détecteur de doublons sur les plus gros fichiers : taille + SHA-256 partiel puis complet ; espace gaspillé par groupe |
| **C — Nettoyage express** | Nettoyage en un endroit : caches/temp, Corbeille (API Windows officielle), gros fichiers des Téléchargements avec sélection multiple (`1,3-5`) — tout confirmé avant suppression |
| **7 — Nettoyage avancé** | Recommandations SAFE / REVIEW / DANGER + conseils système (hiberfil.sys, Windows.old, WinSxS, Optimisation de la livraison) avec la commande de nettoyage officielle |
| **8 — Rapport** | Rapport de stockage complet, exportable en `report.txt`, `report.json`, `report.html`, `report.csv` (compatible Excel) |
| **9 — Recherche** | `/large 10GB`, `/old 1year`, `/files .iso`, `/drive D:`, recherche en texte libre |
| **M — RAM & Processus** | Pression mémoire en direct, plus gros consommateurs de RAM, éléments de démarrage (logon) et services en cours (noyau C++ natif, repli ctypes) + action sûre « libérer le jeu de travail de l'app » |
| **S — Paramètres** | Bascule dry-run, purge du cache, rescan, applis Store on/off, **langue** |

## Lancer — un seul fichier, tout s'auto-installe

**Windows :** double-cliquez (ou exécutez) `run.bat` — au premier lancement il
trouve Python (même hors PATH via le lanceur `py`), crée `.venv`, installe
`rich` + `send2trash`, puis démarre l'application. Les arguments passent directement :

```bat
run.bat --quick
run.bat --selftest
```

**Git Bash / WSL / Linux / macOS :** la même chose avec un seul fichier :

```sh
./run.sh --selftest
```

## Langue — anglais par défaut, changeable à tout moment

Toute l'interface est **en anglais par défaut** et chaque menu, invite, tableau et
rapport passe par une petite couche i18n autonome (`i18n.py`). Changez la langue en
direct via **`S` — Paramètres → `[L] Langue`** ; le choix est persisté dans
`%LOCALAPPDATA%\DiskScope\config.json`. Cinq langues sont fournies :
**anglais, français, espagnol, allemand, italien**.

```bat
run.bat --lang fr            drapeau ponctuel
set DISKTOP_LANG=it          override par variable d'environnement
```

Les clés manquantes retombent sur l'anglais, puis sur la clé elle-même : une
traduction partielle ne peut jamais faire planter l'application.

## Noyau natif — un vrai moteur C++ (`native/`)

Derrière la vue « RAM & Processus » se trouve **`dtk`**, le *DiskTop Core*, une
petite boîte à outils C++ multiplateforme (`native/*.cpp`, binaire unique, sortie JSON) :

```text
dtk mem       mémoire en direct + top consommateurs
dtk proc      chaque processus avec sa RAM (working set) réelle
dtk startup   entrées de registre au logon (démarrage)
dtk svc       inventaire des services Windows
dtk disk      volumes + espace libre
dtk tmp DIR   taille récursive rapide d'un dossier (sans jamais suivre une jonction)
dtk trim      rendre le jeu de travail DE CE processus à l'OS
```

Il s'appuie sur l'API Win32 (`GlobalMemoryStatusEx`, instantanés Toolhelp32,
`GetProcessMemoryInfo`, le gestionnaire de services, les clés de registre `Run`) et,
ailleurs, sur `/proc` POSIX. Il est **100 % facultatif** : les lanceurs le compilent
seulement si `g++` existe, `nativehelper.py` l'appelle d'une façon à toute épreuve,
et `memory.py` lit les mêmes valeurs directement en `ctypes` quand le binaire est
absent. `DISKSCOPE_NO_NATIVE=1` le désactive. Le noyau est **en lecture seule** sauf
`trim`, qui ne touche que la propre mémoire de DiskTop.

> **À propos de la barre de langues GitHub :** l'exécution de DiskTop est en Python
> et il embarque un noyau C++ compilé. Le fichier `.gitattributes` marque la colle
> Python, les sources C++ et la documentation/scripts en `linguist-detectable=false`
> afin que le petit utilitaire **C** écrit à la main (`native/dufast.c`) soit la
> langue mise en avant. C'est un simple choix d'affichage du propriétaire du dépôt —
> rien n'est supprimé, le noyau C++ et tous les modules Python restent dans le dépôt,
> et cela ne change ni l'exécution ni les tests.

## Modèle de sécurité

- **Aucune suppression automatique. Jamais.** Chaque retrait exige une confirmation explicite.
- **Le dry-run est le mode par défaut** : rien n'est touché tant que vous ne le désactivez pas dans `S` > `D`.
- Les suppressions partent dans la **Corbeille** via `trash_win` (appel ctypes + Shell Windows qui fonctionne même sur les profils accentués comme `C:\Users\caméléon`), avec `send2trash` en repli.
- Bloqué matériellement par `safety.py` : racines de lecteur, `C:\Windows` + sous-dossiers, `Program Files`, `ProgramData`, traversée `..`, chemins relatifs, le propre dossier de l'app, **et les jonctions NTFS / points de reparse**.
- La seule « action » mémoire est `trim` : elle ne libère que le jeu de travail de DiskTop lui-même, jamais celui d'un autre programme, et ne tue aucun processus.

## Exigences

- Windows 10 ou 11 (dégradé ailleurs pour le développement)
- Python 3.10+ (3.14/3.15 testés)
- `rich`, `send2trash` — auto-installés par `run.bat` / `run.sh` au premier lancement
- Facultatif : un compilateur C/C++ (`gcc` pour `dufast`, `g++` pour le noyau `dtk`) — non requis
- Facultatif : `pyinstaller` pour construire le `DiskTop.exe` mono-fichier (`build_exe.bat`)

## Journal des modifications

### 2.4.0
- **Noyau natif C++ (`dtk`)** : un vrai moteur C++ multiplateforme sous `native/`
  qui lit la mémoire en direct, la RAM par processus, les éléments de démarrage,
  les services, l'espace libre et les tailles de dossiers, et peut libérer son propre
  jeu de travail. Entièrement facultatif et sans risque (repli `ctypes` complet).
- **Nouveau menu « M — RAM & Processus »** : pression mémoire, top consommateurs,
  démarrage au logon et nombre de services en cours.
- **Italien (5ᵉ langue d'interface)** : `en · fr · es · de · it`.
- **Langue mise en avant** : `.gitattributes` présente désormais le noyau C/C++ comme
  langue principale du dépôt (préférence d'affichage uniquement).

La version anglaise complète (`README.md`) conserve l'historique détaillé.
