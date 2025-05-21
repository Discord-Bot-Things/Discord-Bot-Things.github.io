<?php
header('Content-Type: application/json');
header('Cache-Control: no-cache, no-store, must-revalidate');

// Get all files in the current directory
$files = scandir('.');
$fileList = [];

foreach ($files as $file) {
    // Skip hidden files, directories, and this script
    if ($file[0] === '.' || is_dir($file) || $file === 'list-files.php' || $file === 'index.html') {
        continue;
    }
    
    $fileList[] = [
        'name' => $file,
        'size' => filesize($file)
    ];
}

echo json_encode($fileList);
?>
