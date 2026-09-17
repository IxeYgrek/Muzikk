<div align="center">

# Muzikk

**Gestionnaire de demandes et de téléchargement de musique, façon Overseerr.**

Catalogue MusicBrainz, authentification et musicothèque Jellyfin, acquisition via
Soulseek (slskd) et BitTorrent (Prowlarr + qBittorrent), import et tagging
automatiques en lossless.

</div>

---

## Sommaire

- [Ce que fait Muzikk](#ce-que-fait-muzikk)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Premier démarrage](#premier-démarrage)
- [Configuration des services](#configuration-des-services)
- [Modèle de nommage](#modèle-de-nommage)
- [Comment fonctionne l'acquisition](#comment-fonctionne-lacquisition)
- [Variables d'environnement](#variables-denvironnement)
- [Développement](#développement)
- [Dépannage](#dépannage)

---

## Ce que fait Muzikk

- **Recherche** dans MusicBrainz (instance locale en priorité, `musicbrainz.org` en secours)
  par album, par artiste, par piste ou par label : la fiche d'un label liste tout son
  catalogue, prêt à demander.
- **Marque les albums déjà possédés** dans la musicothèque Jellyfin : coche verte pleine
  quand le MBID correspond, coche claire pour une correspondance floue, badge orange
  « améliorable » quand l'album existant n'est pas en lossless.
- **Demandes par album entier** — jamais piste par piste — avec approbation
  administrateur optionnelle et quotas hebdomadaires par utilisateur.
- **Acquisition automatique** : les providers sont interrogés dans l'ordre configuré
  (slskd, trackers publics, trackers privés par défaut). Chaque candidat est noté ;
  au-dessous du seuil, on passe au suivant.
- **Import complet** : vérification d'intégrité (`flac -t` / `ffmpeg`), tagging
  MusicBrainz exhaustif, pochette intégrée et `cover.jpg`, rangement dans la
  bibliothèque selon un modèle de nommage configurable, hardlink pour continuer à seeder,
  puis rescan Jellyfin.
- **Suivi d'artistes et wishlist** : l'onglet *Suivi* liste ce qui manque chez les
  artistes suivis — leurs nouveautés seules, ou toute leur discographie absente, au
  choix par artiste. Rien n'est jamais téléchargé sans un clic.
- **Recherche par piste** : un titre de chanson suffit pour retrouver l'album qui le
  contient, dans la musicothèque comme dans MusicBrainz.
- **Écoute directe** : les albums déjà présents se lisent dans Muzikk, le flux passant
  par l'API plutôt que par un accès direct à Jellyfin, avec file d'attente, lecture
  aléatoire et répétition.
- **Listes de lecture Jellyfin** : celles du compte connecté se consultent, s'écoutent et
  se modifient depuis Muzikk — ajouter une piste ou un album entier, en retirer une,
  créer ou supprimer une liste.
- **Extraits de 30 secondes** pour écouter un morceau qu'on ne possède pas avant de le
  demander, fournis par Deezer puis par iTunes et relayés par l'API.
- **Import local** : un cadre sous la recherche, réservé aux comptes autorisés, pour
  glisser un dossier d'album ou le parcourir depuis l'explorateur. Muzikk propose les
  candidats MusicBrainz (ou accepte un MBID, ou un formulaire manuel), écrit les tags,
  pose `cover.jpg` et `folder.jpg`, puis range les fichiers selon le modèle de nommage.
  Une copie déjà présente n'est remplacée que si la nouvelle est meilleure (lossy →
  lossless), après confirmation.
- **Atelier de métadonnées** (administrateurs) : analyse du dossier musical à la
  recherche des albums sans tag MusicBrainz, sans pochette, aux tags incomplets, en
  doublon ou invisibles pour Jellyfin ; identification via le serveur MusicBrainz local,
  un MBID collé à la main ou une empreinte audio AcoustID ; simulation avant/après puis
  écriture des tags et de la pochette. Deux boutons complètent l'atelier : l'un uniformise
  les pochettes sur disque pour que chaque dossier d'album contienne à la fois `cover.jpg`
  et `folder.jpg`, l'autre envoie à Jellyfin les pochettes de ses albums restés sans image.
- **Activité temps réel** en SSE, avec le journal détaillé de chaque demande : quel
  provider, quel score, pourquoi un candidat a été rejeté.

Tout tourne dans **un seul conteneur** : FastAPI sert l'API et le SPA React, un worker
asyncio interne consomme une file de travaux stockée en SQLite. Pas de Redis, pas de
Postgres.

## Prérequis

| Service | Rôle | Obligatoire |
| --- | --- | --- |
| Jellyfin | Authentification, liste des utilisateurs, musicothèque, rescan | Oui |
| MusicBrainz | Catalogue (recherche, éditions, pistes) | Recommandé (repli public sinon) |
| slskd | Téléchargement Soulseek | Au moins un provider |
| Prowlarr + qBittorrent | Recherche et téléchargement torrent | Au moins un provider |

Un réseau Docker externe partagé — nommé `mediastack` dans le `docker-compose.yml`
fourni — permet à Muzikk de joindre ces conteneurs par leur nom.

> **Les chemins de volumes doivent être identiques d'un conteneur à l'autre.** Si
> qBittorrent écrit dans `/downloads/torrents`, Muzikk doit voir ce dossier au même
> chemin, sinon les hardlinks deviennent des copies (et les fichiers en seed peuvent
> être dupliqués).

## Installation

```bash
git clone https://github.com/IxeYgrek/Muzikk.git muzikk
cd muzikk
cp .env.example .env
$EDITOR .env          # PUID/PGID, MUSIC_LIBRARY, DOWNLOADS_ROOT
docker compose pull
docker compose up -d
```

L'image publiée est `ixeygrek/muzikk` sur [Docker Hub](https://hub.docker.com/r/ixeygrek/muzikk). Ajoutez `--build` à `docker compose up` seulement si vous voulez construire depuis les sources.

L'interface est disponible sur `http://<hôte>:8383`.

Le réseau doit exister au préalable :

```bash
docker network create mediastack   # si ce n'est pas déjà fait
```

### Volumes

| Volume | Contenu |
| --- | --- |
| `/config` | base SQLite, clé de chiffrement, clé JWT, cache des pochettes, logs |
| `MUSIC_LIBRARY_CONTAINER` (`/music`) | bibliothèque Jellyfin, destination des imports |
| `DOWNLOADS_CONTAINER` (`/downloads`) | racine de téléchargement partagée avec slskd et qBittorrent |

Les chemins **hôte** viennent de `MUSIC_LIBRARY` et `DOWNLOADS_ROOT`, les chemins **dans
le conteneur** de `MUSIC_LIBRARY_CONTAINER` et `DOWNLOADS_CONTAINER`. Ces deux dernières
variables existent parce que les autres conteneurs ne voient pas forcément les disques au
même endroit : donnez à Muzikk le chemin que Jellyfin utilise pour la musicothèque, et
celui que slskd et qBittorrent utilisent pour les téléchargements. Rien n'interdit de
monter deux fois le même disque hôte sur deux chemins différents, les hardlinks
continuent de fonctionner puisque le système de fichiers est le même.

## Premier démarrage

Muzikk s'authentifie via Jellyfin : tant que Jellyfin n'est pas configuré, personne ne
peut se connecter. Un assistant d'installation est donc ouvert au premier lancement,
puis définitivement fermé.

1. **Jellyfin** — URL (par exemple `http://jellyfin:8096`) et clé d'API, créée dans
   Jellyfin sous *Tableau de bord → Avancé → Clés d'API*.
2. **Musicothèque** — cochez les bibliothèques musicales à surveiller et indiquez le
   dossier de destination des imports (`/music` par défaut).
3. Les utilisateurs Jellyfin sont importés. Connectez-vous avec un compte
   **administrateur Jellyfin** : il devient administrateur Muzikk.

L'indexation de la musicothèque démarre en tâche de fond. Selon la taille, comptez
quelques minutes avant que les badges « déjà possédé » apparaissent.

## Configuration des services

Tout se règle dans **Administration**, section par section. Chaque service dispose d'un
bouton *Tester la connexion* qui utilise les valeurs affichées à l'écran, y compris non
enregistrées. Les secrets sont chiffrés au repos (Fernet, clé générée dans `/config`) et
renvoyés masqués : laissez le champ masqué pour conserver la valeur existante.

### Jellyfin

| Réglage | Détail |
| --- | --- |
| URL / Clé d'API | Voir l'assistant ci-dessus |
| Bibliothèques surveillées | Limite l'indexation aux bibliothèques musicales choisies |
| Déclencher un scan après import | Appelle `POST /Library/Refresh` une fois l'album rangé |
| Autoriser tous les utilisateurs | Sinon seuls les identifiants listés peuvent se connecter |

Les administrateurs Jellyfin (`Policy.IsAdministrator`) sont administrateurs Muzikk.

### MusicBrainz

Pointez `url` sur votre instance locale (`http://musicbrainz:5000`). La recherche
plein texte exige **Solr** ; sans lui, seules les recherches par identifiant
fonctionnent et Muzikk bascule sur `musicbrainz.org` si le repli est activé.

Les limites de débit sont respectées séparément pour l'instance locale (10 req/s par
défaut) et le serveur public (1 req/s, comme l'exige MusicBrainz).

La page d'accueil cherche par album, artiste, piste ou **label**. MusicBrainz rattache
les labels aux éditions et non aux albums, alors la fiche d'un label parcourt ses
parutions et les replie en albums : un disque pressé cinq fois n'apparaît qu'une fois,
et les cinq pressages servent quand même à reconnaître ce que vous possédez déjà. Le
compteur affiché sur la fiche est donc un nombre de parutions, plus grand que le nombre
de vignettes.

### Pochettes

Cover Art Archive, avec cache disque dans `/config/cache`. Vous pouvez choisir la
taille, l'intégration dans les fichiers et l'écriture d'un `cover.jpg` et d'un
`folder.jpg` par album. Les deux noms existent parce que les lecteurs ne s'accordent
pas : Jellyfin et Kodi lisent les deux, Plex ne regarde que `cover.jpg`, d'autres que
`folder.jpg`. Écrire les deux coûte quelques kilo-octets et supprime la question.

Pour un album du catalogue, Muzikk essaie la pochette de l'édition, puis celle du
release-group. Pour un album que vous possédez déjà, il essaie successivement l'image
de Jellyfin, un fichier `cover.jpg`, `folder.jpg` ou `front.jpg` posé dans le dossier de
l'album, la pochette **embarquée dans les tags** de la première piste, et enfin Cover
Art Archive. Tout ce qui est trouvé est mis en cache et redimensionné.

Quand aucune source n'a d'image — c'est courant pour les mashups, les bootlegs et les
compilations obscures — la vignette affiche un disque par défaut plutôt qu'un cadre vide.
C'est vrai partout : grilles d'albums, résultats par piste, propositions MusicBrainz de la
page Métadonnées et lecteur.

Le bouton *Vider le cache des pochettes* de la section Système force une nouvelle
recherche, utile après avoir ajouté des pochettes manquantes à votre bibliothèque. Le
cache est purgé automatiquement quand vous changez l'URL du service.

### slskd

| Réglage | Détail |
| --- | --- |
| URL | `http://slskd:5030` |
| Clé d'API | Dans `slskd.yml`, section `web.authentication.api_keys` |
| Préfixe d'URL | À renseigner si slskd tourne derrière un sous-chemin |
| Dossier de téléchargement | Chemin **vu par Muzikk**, par défaut `/downloads/slskd` |
| Durée de recherche | En millisecondes — slskd interprète cette valeur en ms malgré sa documentation |
| Vitesse minimale / file maximale du pair | Filtre les pairs trop lents ou saturés |

Assurez-vous que la clé d'API slskd autorise l'adresse du conteneur Muzikk (`cidr`).

Le **dossier de téléchargement** est le réglage le plus souvent mal renseigné. slskd et
Muzikk voient chacun le disque à travers leurs propres montages, et c'est le chemin côté
Muzikk qu'il faut indiquer ici. Si slskd écrit dans `/media/wdred/downloads/complete/soulseek`
au sens de son propre conteneur, montez le même volume dans Muzikk et saisissez le chemin
correspondant. Le test de connexion de la section slskd vérifie que Muzikk sait lire ce
dossier et refuse de valider sinon : un transfert réussi dont les fichiers sont introuvables
serait téléchargé pour rien.

### Prowlarr

| Réglage | Détail |
| --- | --- |
| URL | `http://prowlarr:9696` |
| Clé d'API | *Settings → General → API Key* |
| Catégories | `3000` (Audio), `3010` (MP3), `3040` (Lossless) par défaut |
| Recherche musicale dédiée | Utilise `type=music` quand l'indexeur le supporte |
| Vérifier le `.torrent` avant ajout | **À laisser activé** : c'est ce qui évite l'essentiel des faux positifs |

Après avoir enregistré, allez dans **Indexeurs** et lancez la synchronisation. Chaque
indexeur peut être activé, priorisé, classé public/privé et recevoir un seuil de
seeders qui lui est propre.

### qBittorrent

| Réglage | Détail |
| --- | --- |
| URL | `http://qbittorrent:8080`, à adapter si `WEBUI_PORT` est différent |
| Utilisateur / Mot de passe | Vides si l'authentification est désactivée pour le réseau local |
| Catégorie | `muzikk`, créée automatiquement |
| Dossier de téléchargement | Chemin **identique** dans les deux conteneurs |
| Continuer le seed après import | Recommandé pour les trackers privés |

L'authentification a changé avec qBittorrent 5.2 : la connexion réussie renvoie un
`204` vide au lieu d'un `200` contenant `Ok.`, un mauvais mot de passe renvoie `401` au
lieu d'un `200` contenant `Fails.`, et le cookie de session a été renommé. Muzikk gère
les deux générations. Pour interpréter un échec :

- **HTTP 401** — identifiants refusés sur qBittorrent 5.2 et suivants. Sur les versions
  antérieures, ce code signale plutôt un rejet de l'en-tête `Host`, fréquent lorsqu'on
  atteint qBittorrent par son nom de conteneur : décochez alors *Activer la validation
  de l'en-tête Host* dans *Outils → Options → Web UI*.
- **`Fails.`** — identifiants refusés sur qBittorrent 5.1 et antérieurs.
- **HTTP 403** — après quelques échecs, qBittorrent bannit temporairement l'adresse.
  Redémarrez le conteneur pour lever le bannissement.

L'alternative qui évite tout cela est de cocher *Bypass authentication for clients in
whitelisted IP subnets* avec le sous-réseau Docker, puis de laisser le champ Utilisateur
vide dans Muzikk.

### Qualité

Formats lossless acceptés (du meilleur au moins bon), repli compressé optionnel, seuils
de taille par piste, nombre de seeders, tolérance sur le nombre de pistes et **score
minimal** d'acceptation (78 par défaut). Baissez-le si trop d'albums échouent, montez-le
si des mauvais albums passent.

*Exiger l'artiste dans le chemin du candidat* refuse une sortie dont le chemin ne nomme
aucun artiste ressemblant à celui demandé. L'artiste ne pèse que 20 points sur 100, donc
sans cette règle l'album d'un homonyme — même titre, même nombre de pistes, même format —
franchit le seuil et peut être importé à la place du bon. Le prix à payer est le dossier
nommé d'après le seul album, sans son artiste, qui sera refusé lui aussi : décochez la
règle si vos sources sont rangées ainsi.

### Ordre des providers

Réordonnez les groupes `slskd`, `trackers publics` et `trackers privés`. Le premier qui
propose un candidat au-dessus du seuil gagne.

### Métadonnées

Pilote l'atelier de métadonnées, accessible aux administrateurs depuis l'entrée
*Métadonnées* du menu. L'analyse parcourt le dossier de la bibliothèque, groupe les
fichiers par album et signale sept anomalies : absence de tag MusicBrainz, correspondance
seulement probable, pochette manquante, tags incomplets, tags en double, doublon, dossier
invisible pour Jellyfin.

| Réglage | Effet |
| --- | --- |
| Analyse nocturne et heure | relance l'analyse chaque nuit à l'heure indiquée |
| Pistes minimum par album | en dessous, le dossier est considéré comme des pistes isolées |
| Score de confiance | seuil au-dessus duquel une proposition est présentée comme fiable |
| Pochette intégrée / `cover.jpg` / `folder.jpg` | ce qui est écrit lors d'une correction |
| AcoustID | empreinte audio, nécessite une clé d'API gratuite |

Le champ *Coller un MBID ou une URL MusicBrainz* accepte les deux formes. Une URL dit
elle-même ce qu'elle désigne ; un identifiant seul est ambigu, alors Muzikk l'essaie comme
groupe de parutions puis comme parution avant d'abandonner. Les résultats de recherche
n'affichent pas de nombre de pistes : un groupe de parutions n'en a pas, le compte
apparaît une fois l'édition choisie.

Rien n'est écrit sans confirmation : chaque album se simule d'abord champ par champ,
avant et après. Une fois les tags corrigés, le bouton *Réindexer Jellyfin* fait redécouvrir
les dossiers que le serveur média avait ignorés.

### Import local

Le cadre sous la recherche de l'accueil n'apparaît que si le compte a le droit *Peut
importer un dossier*, réglable par utilisateur dans *Administration → Utilisateurs*. Les
administrateurs déjà présents au moment de la mise à jour le reçoivent ; un compte créé
ensuite reste sans ce droit tant qu'on ne l'active pas.

Le navigateur envoie les fichiers au conteneur (un chemin Windows n'y est pas lisible).
Après identification — liste MusicBrainz, MBID collé, ou tags saisis à la main — les
pistes sont renommées comme un import Muzikk (`Artiste/Album (année)/01 Titre.ext`),
taguées, et le dossier reçoit `cover.jpg` et `folder.jpg`. Si l'album est déjà possédé
en lossless, l'import est refusé ; s'il n'existe qu'en lossy et que le dossier déposé
est lossless, Muzikk propose de remplacer l'ancienne copie.

L'anomalie *Tags en double* se traite comme les autres, par le filtre du même nom. Certains
encodeurs ajoutent une valeur au lieu de la remplacer : le champ contient alors deux fois la
même chose, ce que Picard montre en `Dushi; Dushi` et ce que les lecteurs affichent collé,
`DushiDushi`. Un champ n'est signalé que s'il ne porte qu'une seule valeur, écrite plusieurs
fois, majuscules ignorées. Dès que les valeurs diffèrent, rien n'est signalé même si l'une
d'elles revient : un medley nomme ses parties une par une et peut créditer le même artiste sur
la première et la dernière, une piste à plusieurs interprètes garde un identifiant par
interprète. Ce sont des tags multivalués légitimes, et les signaler faisait remonter des albums
sains.

Les tags de la fenêtre de correction sont affichés comme le fait Picard, valeur par valeur :
un bloc pour les tags de l'album, la liste des pistes en dessous, et chaque piste se déplie sur
l'ensemble des tags lus dans son fichier. Une valeur écrite deux fois apparaît telle quelle,
en orange, séparée par un point-virgule — c'est le seul affichage honnête, garder la première
valeur revenait à masquer le problème. La simulation le montre aussi : un champ dont le texte
est déjà le bon est quand même compté comme une modification, puisque la réécriture efface les
tags avant de les recréer et fait donc disparaître le doublement. La correction reste album par
album, avec la simulation puis la confirmation habituelles. Comme ces albums portent en général
déjà leur identifiant MusicBrainz dans leurs tags, aucune recherche n'est nécessaire ; sans
identifiant, identifiez d'abord l'album dans la fenêtre.

Le bouton *Uniformiser les pochettes* ne touche pas aux tags et ne télécharge rien : il
parcourt chaque dossier d'album pour qu'il contienne les deux noms de fichier attendus par
les lecteurs. Si `cover` et `folder` sont déjà là, il passe. S'il n'y en a qu'un, il le
recopie sous l'autre nom en gardant son extension : `folder.png` donne `cover.png`. S'il
n'y en a aucun, la pochette embarquée dans les tags des pistes est extraite, convertie en
JPEG à la taille configurée, puis écrite en `cover.jpg` et `folder.jpg`. Un dossier sans
aucune pochette, ni fichier ni tag, est compté à part plutôt que rempli au hasard. Le
passage est sans effet de bord : le relancer ne change plus rien. Contrairement à l'analyse,
une seule piste suffit pour qu'un dossier soit traité.

Le bouton *Réparer les pochettes Jellyfin* s'attaque au problème inverse : les albums que
Jellyfin affiche sans pochette alors qu'il y en a une sur le disque. Muzikk demande d'abord à
Jellyfin de regarder à nouveau, album par album, ce qui suffit quand le fichier a été ajouté
après le dernier scan. Pour ceux qui restent vides, il envoie l'image lui-même via
`POST /Items/{id}/Images/Primary`, exactement ce que fait *Modifier les images* de l'interface :
cette voie contourne les fournisseurs d'images et fonctionne donc même quand l'extracteur de
pochettes embarquées est défaillant. L'image vient du dossier, puis des tags, puis de Cover Art
Archive. Le rafraîchissement ne demande jamais le remplacement des images existantes : sur une
bibliothèque musicale, cette option supprime les `cover.jpg` des dossiers
([jellyfin#12629](https://github.com/jellyfin/jellyfin/issues/12629)).

Deux détails d'implémentation valent d'être connus. Le corps de la requête d'envoi doit être
l'image **encodée en base64** avec un type MIME explicite — un corps binaire ou un
`Content-Type: image/*` renvoie `400 Incorrect ContentType` — et Muzikk retombe sur l'envoi
binaire si une version future change d'avis. Par ailleurs Jellyfin met le rafraîchissement en
file et répond immédiatement, donc Muzikk attend que la file se vide (20 s plus 0,4 s par album,
7 minutes au maximum) avant de vérifier ce qui manque encore.

Le bouton *Aligner Jellyfin sur les tags* règle le symptôme le plus déroutant : des tags
corrigés sur le disque que Jellyfin continue d'afficher faux. Jellyfin lit les tags d'un fichier
la première fois qu'il le voit puis se fie à sa propre base ; son rafraîchissement par défaut ne
comble que ce qui manque, donc un album nommé d'après un tag doublé garde ce nom indéfiniment.
Une bibliothèque qui enregistre des fichiers NFO aggrave le cas, le mauvais nom resté dans
`album.nfo` étant relu avant les tags.

La passe compare donc les deux côtés — titre, artiste et année de l'album, titre et numéro de
chaque piste — puis procède comme pour les pochettes : d'abord un rafraîchissement complet
(`metadataRefreshMode=FullRefresh` et `replaceAllMetadata=true`, seul mode qui fait relire les
fichiers), et pour ce qui résiste une écriture directe via `POST /Items/{id}`, c'est-à-dire ce
que poste *Modifier les métadonnées* de l'interface : aucun fournisseur consulté, aucun NFO relu.
L'écriture est un aller-retour lecture puis renvoi de l'élément complet, car cet appel applique
tous les champs du corps et en effacerait donc ceux qu'on omettrait. Les images ne sont jamais
touchées, pour la raison ci-dessus.

Le rafraîchissement n'est demandé qu'à l'essai, sur huit albums, et n'est étendu au reste que
s'il en a corrigé au moins un. Sur un serveur qui l'ignore — c'est le cas dès qu'autre chose
écrase les tags — l'insister coûterait une longue attente pour rien, et pire : un rafraîchissement
qui se termine après notre écriture la défait. Le rapport le dit alors franchement, *relecture des
fichiers ignorée par Jellyfin*, et la passe écrit directement.

Les albums dont Jellyfin détient la valeur écrite deux fois passent en tête de file, avant ceux
dont une année diverge simplement. Sans cela, une bibliothèque balayée par ordre alphabétique
dépense tout son quota dans les premières lettres et laisse le défaut visible sous la lettre T
attendre le passage suivant.

Le décalage est cherché deux fois, volontairement. La dernière analyse sert de filtre bon marché
— elle contient déjà ce que déclare chaque dossier, donc repérer les suspects ne lit aucun
fichier — puis les fichiers eux-mêmes sont relus et ont le dernier mot : une analyse plus ancienne
que la dernière correction pousserait sinon des valeurs périmées dans Jellyfin. Un maximum de
400 albums est traité par passage, pour ne pas transformer une bibliothèque très décalée en
tempête d'appels ; un passage qui laisse des albums derrière lui met le suivant en file tout
seul, jusqu'à huit fois, de quoi aligner la bibliothèque entière sans avoir à recliquer. La
chaîne est bornée exprès : une valeur que Jellyfin refuserait de garder ne peut pas boucler
indéfiniment.

La passe est aussi mise en file toute seule après chaque écriture de tags, pour l'album concerné
uniquement : c'est ce qui évite d'avoir à y penser après une correction. Ce passage-là ne
remplace pas le rapport affiché en haut de la page, qui reste celui du dernier passage complet.

L'analyse tourne dans le worker : elle continue si vous changez d'onglet ou fermez la page,
et survit même à un redémarrage du conteneur, qui la remet en file.

Chaque analyse laisse un rapport affiché en haut de la page : nombre de dossiers d'album
trouvés, nombre retenus, puis le sort des autres — moins de pistes que le minimum, dossier
illisible, tags illisibles. Le compteur *Albums analysés* rappelle en plus le nombre
d'albums connus de Jellyfin, et `/config/logs/muzikk.log` nomme chaque dossier écarté.

Chaque format est lu selon son conteneur : ID3 pour MP3, WAV et AIFF, atomes iTunes pour
MP4, commentaires Vorbis pour FLAC, Ogg et Opus, et attributs WM pour les WMA. Le genre est
signalé quand il manque mais ne suffit pas à déclarer un album incomplet, sinon presque
toute une bibliothèque se retrouverait marquée.

Un dossier dont les tags résistent n'est jamais perdu : il est listé d'après son nom de
dossier, marqué *sans identifiant* et *tags incomplets*, et sa fiche affiche l'erreur
rencontrée. Le rapport donne en plus les premiers dossiers fautifs avec leur message, de
quoi diagnostiquer sans ouvrir un terminal.

Si l'analyse ne trouve rien du tout, la page affiche la raison exacte renvoyée par le worker
(dossier vide, volume non monté, droits insuffisants, minimum de pistes trop haut) : le
chemin analysé est celui de *Nommage → Dossier de la bibliothèque*, qui doit pointer sur la
bibliothèque réelle et pas seulement sur la destination des imports.

L'empreinte audio dépend de `fpcalc`, fourni par le paquet `libchromaprint-tools` de
l'image. Si l'image a été construite avant cette fonctionnalité, reconstruisez-la.

### Lecteur

Active la lecture dans Muzikk. Cliquez sur une piste de la fiche album, ou sur un résultat
de l'onglet *Pistes*, pour démarrer directement dessus ; la file d'attente reste accessible
depuis le lecteur.

Par défaut Muzikk lit le fichier directement dans le dossier de la bibliothèque, en
retrouvant le chemin même si Jellyfin le voit sous un autre point de montage. C'est plus
rapide et cela ne dépend d'aucune politique de lecture Jellyfin. Décochez *Lire les fichiers
depuis le dossier de musique* si la bibliothèque n'est visible que par Jellyfin : le flux est
alors relayé par l'API, le navigateur ne recevant jamais de jeton. Les formats exotiques
(APE, DSF, WavPack) passent toujours par Jellyfin, qui les transcode.

Le débit maximum, en bit/s, s'applique à ce relais ; `0` diffuse le fichier d'origine. Les
écoutes peuvent être remontées à Jellyfin, sous le compte de l'auditeur — ce qui suppose
qu'il s'est reconnecté à Muzikk depuis l'activation de la lecture, le temps que son jeton
soit mémorisé.

### Listes de lecture

L'onglet *Listes de lecture* montre celles du compte Jellyfin connecté. Une liste s'écoute
depuis Muzikk, piste par piste ou d'un bloc, et se modifie : le bouton *Ajouter à une liste
de lecture* apparaît sur la fiche d'un album — il y ajoute l'album entier, dans l'ordre des
disques et des pistes — comme sur chaque résultat de l'onglet *Pistes* déjà possédé. Le
détail d'une liste permet d'en retirer une piste, et de supprimer la liste si Jellyfin
autorise l'auditeur à le faire.

Tout passe par le jeton de l'auditeur, jamais par la clé API du serveur : une liste
appartient à un compte, et la clé les rangerait toutes sous celui qui la détient. Une liste
créée depuis Muzikk est donc une liste Jellyfin ordinaire, visible dans tous les clients.
Le message *Aucune session Jellyfin pour ce compte* signifie simplement que le jeton n'a pas
été mémorisé : il suffit de se déconnecter puis de se reconnecter à Muzikk.

### Écouter un morceau qu'on ne possède pas

Sur la fiche d'un album absent de la musicothèque, cliquer sur une piste en joue un extrait
de trente secondes ; même chose sur les résultats non possédés de l'onglet *Pistes*, via le
bouton casque de la pochette. Le lecteur affiche alors la pastille *Extrait 30 s*, et l'écoute
n'est pas remontée à Jellyfin : il n'y a aucun morceau de la bibliothèque derrière.

L'extrait vient de Deezer, dont la recherche publique ne demande aucune clé et renvoie un MP3,
et d'iTunes en repli. Chaque réponse est comparée à l'artiste et au titre demandés : une
version karaoké ou un groupe hommage, qui répondent parfaitement sur le titre, sont écartés
sur l'artiste. Quand aucun des deux services ne propose quelque chose de convaincant, Muzikk
le dit plutôt que de jouer autre chose.

Le son est relayé par l'API, comme celui de la bibliothèque : le navigateur ne contacte ni
Deezer ni Apple, et la pochette montrée reste celle que Muzikk affichait déjà. Décochez
*Proposer des extraits de 30 secondes* dans les réglages du lecteur pour que le serveur ne
sorte plus du tout vers ces deux services.

## Modèle de nommage

Le modèle par défaut reproduit le script Picard demandé :

```
{albumartist}/{album} ({year})/{disc_prefix}{track:02} {artist_prefix}{title}
```

donnant `Daft Punk/Discovery (2001)/03 Digital Love.flac`.

| Variable | Valeur |
| --- | --- |
| `{albumartist}` `{artist}` | artiste de l'album / de la piste |
| `{album}` `{title}` | titre de l'album / de la piste |
| `{year}` `{date}` | année, date complète de sortie |
| `{track}` `{disc}` `{totaldiscs}` | numéros ; `{track:02}` pour deux chiffres |
| `{disc_prefix}` | vide sur un disque unique, `1-` sinon, `01-` au-delà de neuf disques |
| `{artist_prefix}` | vide, sauf sur un album multi-artistes où il vaut `Artiste - ` |
| `{ext}` | extension du fichier, ajoutée automatiquement si absente |

L'aperçu se met à jour en direct pendant l'édition, sur trois exemples représentatifs
(album simple, coffret multi-disques, compilation).

> Les téléchargements Soulseek sont liés en dur puis étiquetés sur place. Les torrents
> sont **copiés** avant tagging : réécrire les tags d'un fichier en cours de seed le
> corromprait aux yeux du tracker.

## Comment fonctionne l'acquisition

```
demande → (approbation) → recherche → candidat retenu → téléchargement
        → vérification → tagging → import → rescan Jellyfin
```

Avant toute recherche, Muzikk inspecte le dossier de téléchargement de slskd : si l'album
s'y trouve déjà en entier, il est importé directement, sans repasser par le réseau. Le
dossier candidat est noté exactement comme un candidat distant — format, nombre de pistes,
titres, taille par piste — donc un téléchargement partiel ou un autre album ne peut pas
être pris par erreur. C'est ce qui évite de re-télécharger un album quand un import a
échoué pour une raison de configuration.

Ensuite, pour chaque provider, dans l'ordre configuré :

1. Recherche à partir de l'artiste, du titre normalisé, de l'année et du nombre de pistes.
   Jusqu'à quatre variantes du terme sont essayées, chacune laissant tomber quelque chose
   que le pair n'a peut-être pas écrit : d'abord le type de sortie — Soulseek ne répond que
   si **tous** les mots figurent dans le chemin, donc chercher « Pharaoh EP » ne trouve
   jamais un dossier nommé « Eekoz - Pharaoh » — puis les mentions d'édition. Le titre seul,
   sans l'artiste, passe en dernier : c'est le seul terme qui ramène des centaines de
   dossiers sans rapport, et le demander tôt saturait la liste de candidats avant que les
   termes nommant l'artiste aient eu leur tour.
2. Notation de chaque candidat : similarité artiste et titre (`rapidfuzz` après
   suppression des accents, de la ponctuation et des mentions « deluxe », « remaster »…),
   correspondance du nombre de pistes, couverture des titres de pistes, format détecté,
   cohérence de la taille par piste, seeders ou vitesse du pair.
3. Pour les torrents, le `.torrent` est téléchargé et **sa liste de fichiers est lue
   avant l'ajout** à qBittorrent. Pour slskd, les résultats sont regroupés par dossier
   distant, et un dossier ne contenant qu'un seul fichier audio est écarté — une piste
   isolée qui porte le nom de l'album n'est pas l'album. Sauf pour un single : quand
   MusicBrainz annonce une seule piste, un seul fichier suffit, sinon la sortie était
   jetée avant même d'être notée.
4. Le meilleur candidat au-dessus du seuil est mis en file ; sinon on passe au provider
   suivant. Si tous échouent, la demande passe en échec et sera relancée automatiquement.

Le journal de chaque demande conserve tous les candidats évalués avec leur score et le
motif de rejet, visible depuis la page **Demandes**.

Trois actions de masse sont disponibles en haut de cette page, chacune traitant toute la
liste concernée et pas seulement les lignes affichées : vider les demandes importées,
vider les demandes en échec, annuler les demandes actives. Une annulation n'interrompt
pas le transfert à l'instant même : le pipeline s'en aperçoit à sa prochaine mesure de
progression et abandonne alors le téléchargement en cours.

### Valider une amélioration avant de supprimer l'ancienne version

Une amélioration atterrit presque toujours dans le dossier qu'elle améliore : le schéma
de nommage donne le même artiste, le même album et la même année. Les anciens MP3 et les
nouveaux FLAC se retrouvent donc côte à côte dans un seul dossier — que supprimer le
dossier entier était justement refusé de faire, puisqu'il contient désormais les nouveaux
fichiers. Résultat : les anciens fichiers survivaient, et Jellyfin affichait chaque piste
deux fois.

Désormais, à la fin de l'import d'une amélioration, Muzikk relève les deux versions
fichier par fichier — format, résolution, débit, durée, taille — et met la demande en
statut **À valider** sans rien supprimer. Le demandeur ou un administrateur ouvre la
demande, compare les deux colonnes, puis choisit :

- **Valider** supprime les anciens fichiers audio uniquement, en gardant la pochette du
  dossier et les pistes qui viennent d'être écrites. Si le nouveau dossier est ailleurs,
  l'ancien est supprimé en entier.
- **Refuser** fait l'inverse : les fichiers fraîchement importés sont supprimés et
  l'ancienne version reste en place. Seule la pochette du dossier, réécrite à l'import,
  ne peut pas être restaurée.

Le relevé des anciens fichiers est pris **avant** de placer les nouveaux, sans quoi un
fichier de même nom et même extension serait écrasé avec la preuve de ce qu'il était. Un
fichier ainsi remplacé n'est jamais proposé à la suppression : il contient déjà la
nouvelle version.

Le réglage *Demander une validation avant de supprimer l'ancienne version* (section
Nommage) désactive cette étape : la suppression redevient immédiate, mais elle porte
maintenant aussi sur les anciens fichiers d'un dossier partagé, ce qu'elle ne faisait
pas. Et *Supprimer l'ancienne version après une amélioration* continue, s'il est
désactivé, à tout conserver sans rien demander.

### Suivre un artiste sans rien télécharger

Suivre un artiste ne déclenche aucun téléchargement. La vérification périodique compare
sa discographie MusicBrainz à la musicothèque et écrit ce qui manque ; l'onglet **Suivi**
l'affiche, et chaque album attend un clic. C'est un choix délibéré : télécharger d'office
les nouveautés de quelques dizaines d'artistes suivis remplit le disque de disques que
personne n'a demandés.

Chaque artiste suivi a sa propre portée, réglable sur sa ligne :

- **Nouveautés** ne montre que les sorties de moins de 400 jours.
- **Discographie** montre tout ce qui manque, quelle que soit l'année.

Albums, EP et singles comptent dans les deux cas, une pastille sur la pochette rappelant
de quoi il s'agit quand ce n'est pas un album. Les compilations, albums live, remixes et
autres types secondaires sont écartés : on suit un artiste pour sa discographie, pas pour
ses rééditions. Changer la portée relance une vérification, puisque la liste en dépend.

La liste se filtre par artiste, ou sur les seules nouveautés. L'œil barré sur une
pochette met l'album de côté : il passe dans *Ignorés* et n'en ressort que si vous le
restaurez, même après une nouvelle vérification. Un album disparaît de lui-même quand la
musicothèque finit par le contenir.

La **wishlist** reste une liste tenue à la main, alimentée par le bouton *Ajouter à la
wishlist* d'une fiche album. Elle ne relance plus rien automatiquement : le bouton
*Vérifier* solde simplement les entrées que la musicothèque contient désormais, et chaque
ligne garde son propre bouton de demande.

## Variables d'environnement

Seules l'infrastructure et les chemins passent par l'environnement ; tout le reste se
configure dans l'interface.

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `PUID` / `PGID` | `1000` | Propriétaire des fichiers écrits, doit correspondre à la bibliothèque |
| `UMASK` | `002` | Masque appliqué aux fichiers importés |
| `TZ` | `Europe/Paris` | Fuseau horaire du conteneur |
| `MUZIKK_PORT` | `8383` | Port HTTP |
| `MUZIKK_CONFIG_DIR` | `/config` | Base, clés, cache, logs |
| `MUZIKK_STATIC_DIR` | `/app/static` | SPA compilé |
| `MUZIKK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` |
| `MUZIKK_WORKER_CONCURRENCY` | `2` | Travaux traités en parallèle (1 à 8) |
| `MUZIKK_SESSION_HOURS` | `336` | Durée de validité d'une session |

Côté `docker-compose`, `MUSIC_LIBRARY` et `DOWNLOADS_ROOT` désignent les chemins **hôte**,
`MUSIC_LIBRARY_CONTAINER` et `DOWNLOADS_CONTAINER` les chemins correspondants **dans le
conteneur**.

## Développement

Backend :

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
MUZIKK_CONFIG_DIR=./config .venv/bin/uvicorn muzikk.main:app --reload --app-dir backend --port 8383
```

Frontend :

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, /api est relayé vers le port 8383
```

Contrôles rapides, sans Node ni Docker :

```bash
.venv/bin/python -m ruff check backend      # lint
.venv/bin/python backend/smoke_test.py      # démarrage, routes et gardes d'authentification
.venv/bin/python backend/pipeline_test.py   # nommage, matching, association fichiers/pistes
.venv/bin/python backend/artwork_test.py    # résolution des pochettes
.venv/bin/python backend/metadata_test.py   # analyse de la bibliothèque et lecture des tags
.venv/bin/python backend/local_import_test.py # import d'un dossier local, tags et nommage
.venv/bin/python backend/playback_test.py   # localisation des fichiers et requêtes Range
.venv/bin/python frontend/check_frontend.py # imports et clés de traduction
```

Une migration Alembic se génère avec :

```bash
cd backend && alembic revision --autogenerate -m "description"
```

Les migrations sont appliquées automatiquement au démarrage ; sur une base vierge, le
schéma est créé puis marqué à la dernière révision.

## Dépannage

**« La recherche ne renvoie rien »** — l'instance MusicBrainz locale n'a probablement pas
Solr. Le test de connexion l'indique explicitement. Activez le repli public en attendant.

**« Aucun candidat n'est accepté »** — ouvrez la demande : chaque candidat évalué affiche
son score et son motif de rejet. Les causes fréquentes sont un nombre de pistes différent
(édition MusicBrainz mal choisie : forcez une autre édition depuis la fiche album), un
score trop juste (baissez le seuil dans *Qualité*) ou un manque de seeders.

**« Le même album est téléchargé en boucle »** — le journal de la demande contient alors
`the downloaded files could not be located on disk`. slskd a bien récupéré l'album, mais
Muzikk ne retrouve pas les fichiers et considère le candidat comme raté. Corrigez le
**dossier de téléchargement** de la section slskd (voir plus haut) puis relancez la
demande : les fichiers déjà présents seront importés sans être retéléchargés. Muzikk
arrête désormais immédiatement la demande dans ce cas au lieu d'essayer les candidats
suivants, et ne programme pas de nouvelle tentative automatique tant que la configuration
n'a pas été corrigée.

**« Les fichiers sont copiés au lieu d'être liés »** — les chemins `/downloads` et
`/music` doivent être sur le **même système de fichiers** et montés au même endroit dans
tous les conteneurs. Un montage réseau distinct force la copie.

**« Jellyfin ne voit pas les nouveaux albums »** — vérifiez `PUID`/`PGID` et `UMASK` :
Jellyfin doit pouvoir lire les fichiers. Le rescan automatique peut aussi être désactivé
dans les réglages Jellyfin de Muzikk. Si un dossier reste invisible malgré un rescan, il
apparaît dans *Métadonnées* sous « Absent de Jellyfin » : c'est presque toujours un album
sans tag `album` ou `albumartist`, que le serveur média ne sait pas classer. Corrigez les
tags depuis cette page puis relancez la réindexation. Le rapprochement essaie le chemin
exact, puis les deux derniers segments du chemin, puis l'identifiant MusicBrainz — Jellyfin
peut donc renommer un album sans le faire disparaître — et le nom en dernier recours.

**« La lecture ne démarre pas »** — le lecteur affiche désormais le motif exact renvoyé par
le serveur à côté de « Lecture impossible ». La section *Lecteur* doit être activée et, si la
lecture directe est désactivée, Jellyfin joignable depuis le conteneur. Un compte connecté
avant l'activation de la lecture n'a pas encore de jeton mémorisé : la lecture retombe sur
la clé d'API du serveur et l'écoute n'est pas créditée, une reconnexion suffit.

**« Je ne peux pas me connecter »** — Muzikk ne stocke aucun mot de passe : l'échec vient
de Jellyfin. Vérifiez que l'utilisateur est actif dans Muzikk (*Administration →
Utilisateurs*) et que la clé d'API Jellyfin est toujours valide.

Les journaux détaillés se trouvent dans `/config/logs/muzikk.log` et dans
`docker compose logs -f muzikk`. Les deux reçoivent la même chose ; une version antérieure
laissait Alembic reprendre la configuration des journaux au démarrage, ce qui arrêtait
l'écriture du fichier juste après les migrations.
