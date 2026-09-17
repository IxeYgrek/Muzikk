<?php
/**
 * Serves one slideshow image from a folder that may sit outside the site
 * root (Images/Screenshot next to Website/). Only a file name is accepted.
 */

declare(strict_types=1);

require __DIR__ . '/includes/bootstrap.php';

$name = isset($_GET['f']) && is_string($_GET['f']) ? $_GET['f'] : '';
$file = screenshot_file($name);
if ($file === null) {
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    echo 'Screenshot not found.';
    exit;
}

$type = @mime_content_type($file);
if (!is_string($type) || !str_starts_with($type, 'image/')) {
    $type = 'application/octet-stream';
}

header('Content-Type: ' . $type);
header('Content-Length: ' . (string) filesize($file));
header('Cache-Control: public, max-age=86400');
header('X-Content-Type-Options: nosniff');
readfile($file);
