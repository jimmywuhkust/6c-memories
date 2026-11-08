<?php
// Public content only: never export account emails, password hashes, IPs or unapproved comments.
$host = explode(':', getenv('WORDPRESS_DB_HOST'));
$db = new mysqli($host[0], getenv('WORDPRESS_DB_USER'), getenv('WORDPRESS_DB_PASSWORD'), getenv('WORDPRESS_DB_NAME'), isset($host[1]) ? (int)$host[1] : 3306);
if ($db->connect_errno) throw new RuntimeException($db->connect_error);
$db->set_charset('utf8mb4');
function rows($sql) { global $db; $r=$db->query($sql); if (!$r) throw new RuntimeException($db->error); return $r->fetch_all(MYSQLI_ASSOC); }
$settings=[];
foreach (rows("SELECT option_name,option_value FROM wp_options WHERE option_name IN ('blogname','blogdescription','siteurl','home','permalink_structure','theme_mods_twentyseventeen')") as $r) $settings[$r['option_name']]=$r['option_value'];
$mods=unserialize($settings['theme_mods_twentyseventeen'], ['allowed_classes'=>false]);
unset($settings['theme_mods_twentyseventeen']);
$theme=array_intersect_key($mods ?: [], array_flip(['header_image','header_image_data','custom_logo','background_color','colorscheme','panel_1','panel_2','panel_3','panel_4']));
$posts=rows("SELECT ID,post_date,post_modified,post_title,post_content,post_excerpt,post_name,post_type,post_parent,post_mime_type,menu_order,comment_status FROM wp_posts WHERE (post_status='publish' AND post_type IN ('post','page','nav_menu_item')) OR (post_status='inherit' AND post_type='attachment') ORDER BY ID");
foreach ($posts as &$post) {
    $id=(int)$post['ID'];
    $post['meta']=[];
    foreach (rows("SELECT meta_key,meta_value FROM wp_postmeta WHERE post_id=$id AND meta_key IN ('_wp_attached_file','_wp_attachment_metadata','_thumbnail_id','_menu_item_object_id','_menu_item_type','_menu_item_url')") as $m) {
        $value=$m['meta_value'];
        if ($m['meta_key']==='_wp_attachment_metadata') $value=unserialize($value, ['allowed_classes'=>false]);
        $post['meta'][$m['meta_key']]=$value;
    }
}
unset($post);
$comments=rows("SELECT comment_ID,comment_post_ID,comment_author,comment_date,comment_content,comment_parent FROM wp_comments WHERE comment_approved='1' AND comment_type IN ('comment','') ORDER BY comment_date");
echo json_encode(['site'=>$settings,'theme'=>$theme,'posts'=>$posts,'comments'=>$comments], JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_PRETTY_PRINT|JSON_THROW_ON_ERROR), "\n";
