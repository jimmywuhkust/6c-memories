<?php
// Operates only on the restored local database. No WordPress plugins are loaded.
$db = new mysqli(getenv('WORDPRESS_DB_HOST'), getenv('WORDPRESS_DB_USER'), getenv('WORDPRESS_DB_PASSWORD'), getenv('WORDPRESS_DB_NAME'));
if ($db->connect_errno) { throw new RuntimeException($db->connect_error); }
$db->set_charset('utf8mb4');
$from = ['https://6c2021msc.ddns.net', 'http://6c2021msc.ddns.net'];
$to = 'http://localhost:8086';
function replace_value($v) {
    global $from, $to;
    if (is_string($v)) return str_replace($from, $to, $v);
    if (is_array($v)) {
        $out = [];
        foreach ($v as $k => $item) $out[is_string($k) ? str_replace($from, $to, $k) : $k] = replace_value($item);
        return $out;
    }
    return $v;
}
function relocate($value) {
    global $from, $to;
    if (!is_string($value) || (!str_contains_compat($value, $from[0]) && !str_contains_compat($value, $from[1]))) return $value;
    $decoded = @unserialize($value, ['allowed_classes' => false]);
    if ($decoded !== false || $value === 'b:0;') {
        // Leave serialized objects unchanged rather than alter unavailable classes.
        if (strpos($value, 'O:') !== false || strpos($value, 'C:') !== false) return $value;
        return serialize(replace_value($decoded));
    }
    return str_replace($from, $to, $value);
}
function str_contains_compat($s, $needle) { return strpos($s, $needle) !== false; }
$changed = 0;
$tables = $db->query('SHOW TABLES');
while ($table = $tables->fetch_row()) {
    $name = $table[0];
    if (strpos($name, 'wp_') !== 0 || !preg_match('/^[a-zA-Z0-9_]+$/', $name)) continue;
    $cols = $db->query("SHOW COLUMNS FROM `$name`");
    $pk = []; $text = [];
    while ($col = $cols->fetch_assoc()) {
        if ($col['Key'] === 'PRI') $pk[] = $col['Field'];
        if (preg_match('/char|text|blob/', $col['Type']) && $col['Field'] !== 'guid') $text[] = $col['Field'];
    }
    if (!$pk || !$text) continue;
    $rows = $db->query("SELECT * FROM `$name`");
    while ($row = $rows->fetch_assoc()) {
        $sets = [];
        foreach ($text as $col) {
            $next = relocate($row[$col]);
            if ($next !== $row[$col]) $sets[] = "`$col`='" . $db->real_escape_string($next) . "'";
        }
        if (!$sets) continue;
        $where = [];
        foreach ($pk as $col) $where[] = "`$col`='" . $db->real_escape_string($row[$col]) . "'";
        if (!$db->query("UPDATE `$name` SET " . implode(',', $sets) . ' WHERE ' . implode(' AND ', $where))) throw new RuntimeException($db->error);
        $changed++;
    }
}
echo json_encode(['local_rows_relocated' => $changed]), "\n";
