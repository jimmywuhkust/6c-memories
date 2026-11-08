# 6C 回憶錄

原 WordPress 网站的完整本地备份，以及适合 GitHub Pages 的静态新版。

## 本地预览

- 原站 Docker 还原版：[localhost:8086](http://localhost:8086/)
- 静态新版：[localhost:8087](http://localhost:8087/)
- [相册](http://localhost:8087/image-gallery/) · [视频](http://localhost:8087/video-gallery/) · [匿名投稿](http://localhost:8087/say-something/)

启动已准备好的两个版本：

```sh
docker compose --profile modern up -d
```

停止：

```sh
docker compose --profile modern down
```

停止容器会保留本地数据库。完整原始备份在 `backups/2026-11-08/`，本地 WordPress 工作副本在 `local-wordpress/`；这些目录不进入 Git 仓库。

## 内容与构建

`data/content.json` 保留原站已公开的页面和文章内容；`assets/media/` 保留原媒体文件及 WordPress 已有的图片尺寸。原文、71 张相册图片和 5 个视频的顺序保持一致。视频标题与封面来自原有视频的 YouTube 元数据。YouTube 视频本体原先就不在 WordPress 中，本地保留的是链接与嵌入。

```sh
python3 scripts/build_site.py
python3 scripts/check_site.py
```

仅用 Python 标准库构建，产物在 `dist/`。页面不依赖 WordPress/PHP。所有站内链接使用相对路径，可部署到 GitHub Pages 的项目子目录。相册按照片比例计算完整的等高行，保留原始顺序并填满版面；顶部每次随机选取六张原照片。各页面标题有逐字出现动画，并适配减少动画的系统设置。照片支持点击放大、前后切换、手机滑动和下载原图。音乐需要点击播放。

原站未公开的评论、账号数据和插件表单数据只保存在本地完整数据库备份中。

## 匿名投稿

Docker 新版已提供本地匿名投稿服务，支持标题、正文、可选名字和可选照片。记录保存在 `private/guestbook.sqlite`，照片保存在 `private/guest-photos/`。新投稿默认待审核；未审核的照片不会公开。此处是本地验证环境，不是已开通的线上留言服务。

线上方案已准备为 Supabase 托管数据库、私有照片存储和一个 Edge Function，不要求同学注册账户，也不需要运行 WordPress：

- `supabase/setup.sql`：专用项目的数据库与私有存储设置。
- `supabase/functions/sixc-guestbook/index.ts`：匿名读写接口、输入校验、限流和审核后的照片访问。
- `site.config.json`：正式后端地址和可公开的 publishable key；不得填写 service-role/secret key。

**按当前决定，线上留言暂缓开发与开通。** `commentsEnabled` 当前为 `false`，正式静态站不会接收留言，本地沙盒仍可验证表单。没有创建云端项目或产生服务费用。后端代码保留供后续使用；数据库表结构尚未在真实 Supabase 项目验证。接口已通过本地模拟后端检查；Docker 版已验证文字与照片的提交、审核和读取。

审核由项目所有者在 Supabase 后台修改 `sixc_guest_entries.approved` 完成；浏览器不拥有审核权限。

## GitHub Pages

`.github/workflows/pages.yml` 提供构建及部署流程，发布分支为 `codex/6c-static-site`，GitHub 的 Pages 使用 GitHub Actions。

当前可以先构建不接收留言的静态版本。日后启用 `commentsEnabled` 时，正式构建会要求填写有效留言服务配置：

```sh
python3 scripts/build_site.py --production
```

公开源码：[jimmywuhkust/6c-memories](https://github.com/jimmywuhkust/6c-memories)。网站的目标地址为 [6C 回憶錄](https://jimmywuhkust.github.io/6c-memories/)。只发布静态网站源码及公开媒体；原始数据库、Docker 镜像、密码和私人记录保留在本机。

参考：[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[大小限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)、[Supabase Edge Function 配置](https://supabase.com/docs/guides/functions/function-configuration)。
