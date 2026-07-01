# YouTube Repo - Publish/Post Button Audit Report

## Summary

Audit of the `modom123/youtube` repository (branch `main`) for all "publish", "post", "share", "schedule" buttons in frontend templates and their corresponding backend endpoints.

---

## Detailed Audit Table

| Template | Button Label | JS Function | API Endpoint | Backend Implementation | Actually Publishes? | Notes |
|----------|--------------|-------------|--------------|----------------------|---------------------|-------|
| **job_detail.html** | "Publish Now" (line 469) | `publishNow()` | `POST /api/jobs/<job_id>/publish` | Calls `social_optimize.publish_to_platforms()` | YES - Real | Calls actual publisher functions for each selected platform |
| **job_detail.html** | "Regenerate Thumbnail" (line 232) | `regenThumbnail()` | `POST /api/jobs/<job_id>/thumbnail/regenerate` | Regenerates thumbnail | N/A - Media | Not a publish action |
| **job_detail.html** | "Mix Audio + Video → Final MP4" (line 379) | `mixAudioVideo()` | `POST /api/jobs/<job_id>/mix` | FFmpeg mixing | N/A - Media | Not a publish action |
| **job_detail.html** | "Convert Video" (line 410) | `convertVideo()` | `POST /api/jobs/<job_id>/convert` | Video format conversion | N/A - Media | Not a publish action |
| **job_detail.html** | "Generate New Version" (line 500) | `createReformat()` | `POST /api/create` or `POST /api/studio/run` | Creates new job in different format | N/A - Meta | Doesn't publish, creates new jobs |
| **quickpost.html** | "🚀 Post Now" (line 326) | `postNow(platform, btn)` | `POST /api/quickpost/<job_id>/publish` | Calls `social_optimize.publish_to_platforms()` (for video) or `_quickpost_publish_image()` (for images) | YES - Real (when video); Conditional (when image) | For videos: real publishers. For images: attempts real API calls to social platforms |
| **quickpost.html** | "📅 Schedule" (line 327) | `openSchedule(platform)` | Shows schedule form | N/A - UI only | N/A | UI toggle only |
| **quickpost.html** | "📅 Confirm Schedule" (line 331) | `schedulePost(platform)` | `POST /api/quickpost/<job_id>/publish` with `schedule_at` param | Creates stub job + scheduled post record | NO - Queued only | Doesn't publish; stores job_id for later processing |
| **calendar.html** | "Schedule Post" (line 88) | `schedulePost()` | `POST /api/schedule` | Creates `scheduled_post` DB record | NO - Queued only | Purely database operation; no actual publishing |
| **clipper.html** | "Publish All" (line 11) | `publishAll()` | None | Returns stub toast message | NO - Stub | Displays "Coming Soon" toast |
| **clipper.html** | "Publish" icon for individual clips (line 785) | `publishClip(idx)` | None | Returns stub toast message | NO - Stub | Displays "Coming Soon" toast |
| **engagement.html** | "Queue Action" (line 165) | `quickAction()` | `POST /api/engagement/actions` | Creates engagement action record | NO - Queued only | Queues comments/follows to engagement system, not actual publication |

---

## Backend Endpoint Analysis

### 1. **POST /api/jobs/<job_id>/publish** (app.py:775)
- **Status**: IMPLEMENTED - REAL PUBLISHING
- **What it does**:
  - Validates job exists and is done
  - Extracts metadata (title, description, hashtags, keywords)
  - Calls `social_optimize.publish_to_platforms()`
  - Stores results in DB
  - Returns per-platform results
- **Platforms supported**: YouTube, TikTok, Instagram, Facebook, Twitter, LinkedIn, Pinterest, Threads
- **Real implementation**: YES

### 2. **POST /api/quickpost/<job_id>/publish** (app.py:367)
- **Status**: IMPLEMENTED - REAL PUBLISHING (for videos); CONDITIONAL (for images)
- **What it does**:
  - For immediate publish (no `schedule_at`):
    - If video: Calls `social_optimize.publish_to_platforms()` → REAL
    - If image: Calls `_quickpost_publish_image()` → Attempts real API calls
  - For scheduled publish:
    - Creates stub job record
    - Creates scheduled_post DB entry
    - Returns queued status (NOT published yet)
- **Platforms supported**: Instagram, TikTok, Facebook, Twitter, Twitch, Threads, YouTube, Snapchat
- **Real implementation**: YES for "Post Now"; NO for "Schedule"

### 3. **POST /api/schedule** (app.py:3748)
- **Status**: IMPLEMENTED - DATABASE ONLY (QUEUED)
- **What it does**:
  - Takes job_id, platform, scheduled_at
  - Creates `scheduled_post` record in DB
  - Returns post_id + status "scheduled"
  - Does NOT publish or call any publisher
- **Real implementation**: NO - Just stores in database

### 4. **POST /api/engagement/actions** (app.py:5718)
- **Status**: IMPLEMENTED - DATABASE ONLY (QUEUED)
- **What it does**:
  - Takes platform, action_type, target_url, comment_text, campaign_id
  - Creates engagement_action record in DB
  - Returns "queued" status
  - Does NOT perform the action or call any publisher
- **Real implementation**: NO - Just stores in database

---

## Publisher Module Analysis (`social_optimize.publish_to_platforms()`, lines 761-832)

### Real Publishers (Implemented)
- **YouTube**: ✅ `youtube_publisher.upload_video()` - Full API implementation with authentication, resumable uploads, thumbnail setting
- **TikTok**: ✅ `tiktok_publisher.upload_video()` - Full API implementation with chunked uploads, polling for completion
- **Facebook**: ✅ `facebook_publisher.upload_video()` - Calls real FB Graph API
- **Twitter/X**: ✅ `twitter_publisher.upload_video()` - Calls real Twitter API v2
- **LinkedIn**: ✅ `linkedin_publisher.upload_video()` - Calls real LinkedIn API
- **Pinterest**: ✅ `pinterest_publisher.upload_video()` - Calls real Pinterest API
- **Threads**: ✅ `threads_publisher.upload_video()` - Calls real Threads API (requires CDN URL)

### Stub/Placeholder Publishers
- **Instagram**: ❌ STUB - Returns `{"status": "skipped", "reason": "Instagram requires a public CDN URL. Host the video first."}`
- **Instagram (via instagram_publisher.py)**: ⚠️ Partial - `upload_reel()` exists but requires video to be publicly hosted on CDN (no direct file upload support from Graph API)

---

## Stubs and Placeholders Identified

| Feature | Location | Status | Details |
|---------|----------|--------|---------|
| Clipper Publish All | clipper.html:11, 888 | STUB | Toast message: "Coming Soon" |
| Clipper Publish Single | clipper.html:785, 884 | STUB | Toast message: "Coming Soon" |
| Schedule (Calendar) | calendar.html:88 | QUEUED ONLY | Creates DB record, no actual publishing |
| Schedule (Quickpost) | quickpost.html:331 | QUEUED ONLY | Creates DB record, no actual publishing |
| Engagement Actions | engagement.html:165 | QUEUED ONLY | Creates DB record, no actual publishing |

---

## Summary of Findings

### Working Publish Buttons (Actually Publish)
1. **job_detail.html - "Publish Now"**: Fully functional, calls real publishers
2. **quickpost.html - "Post Now"**: Fully functional for videos; real publishers for images

### Scheduled/Queued (Not Yet Published)
1. **quickpost.html - "Schedule"**: Queues for later; stored in DB
2. **calendar.html - "Schedule Post"**: Queues for later; stored in DB
3. **engagement.html - "Queue Action"**: Queues engagement action; stored in DB

### Broken/Incomplete Stubs
1. **clipper.html - "Publish All"**: Stub - displays "Coming Soon"
2. **clipper.html - Individual Clip "Publish"**: Stub - displays "Coming Soon"

### Platforms with Issues
- **Instagram**: Returns "skipped" with message about CDN requirement (no direct file upload support)
- **Threads**: Returns "skipped" unless cdn_url is provided

---

## Code References

- Main app file: `/tmp/repo_push/app.py`
- Social optimization module: `/tmp/repo_push/social_optimize.py`
- Publishers directory: `/tmp/repo_push/publishers/`
- Frontend templates: `/tmp/repo_push/templates/`
  - `job_detail.html` (lines 469, 232, 379, 410, 500)
  - `quickpost.html` (lines 326, 327, 331)
  - `calendar.html` (line 88)
  - `clipper.html` (lines 11, 785, 884-890)
  - `engagement.html` (line 165)
