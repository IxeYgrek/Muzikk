# Screenshots

Drop your captures in this folder. The slideshow on the home page reads the
folder at each request, so nothing has to be declared in the code.

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

A caption is looked up in the language files under
`home.shots.captions.<slug>`, where the slug is the file name without its
leading number and without its extension — `03-album.png` looks for
`home.shots.captions.album` in `lang/en/home.php`.

Without a match, the file name itself is tidied up and used, so a screenshot is
never left unlabelled. A few captions are already written for the usual names:
`home`, `search`, `album`, `requests`, `library`, `metadata`, `admin`, `player`.

## Format

The slideshow shows every image inside a fixed 16:10 window, scaled to fit, so
the page never jumps when the slide changes. Captures taken on a 16:9 or 16:10
window therefore fill the frame best. Around 1600 px wide is plenty.
