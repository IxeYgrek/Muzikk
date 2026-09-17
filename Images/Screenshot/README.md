# Screenshots

Drop your captures in this folder. The slideshow on the home page reads it
at each request, so nothing has to be declared in the code.

## Order

Files are sorted by name, naturally, so number them:

```
01-home.png
02-search.png
03-album.png
04-requests.png
05-metadata.png
06-admin.png
```

Accepted extensions: `jpg`, `jpeg`, `png`, `webp`, `avif`, `gif`.

## Captions

A caption is looked up in `Website/lang/en/home.php` under
`home.shots.captions.<slug>`, where the slug is the file name without its
leading number and without its extension — `03-album.png` looks for
`album`. Without a match, the file name itself is tidied up and used.

A few captions are already written for: `home`, `search`, `album`,
`requests`, `library`, `metadata`, `admin`, `player`.
