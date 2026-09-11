# posts/buffer/ — قائمة انتظار المنشورات

وضع ملف JSON هنا في PR نحو `main` يجهّز المنشور فقط. بعد مراجعة الـPR ودمجه،
يشغّل `push` إلى `main` النشر في Buffer. فتح الـPR أو تحديثه لا ينشر شيئًا.

## الحقول

| الحقل       | مطلوب | الوصف |
|-------------|-------|-------|
| `text`      | نعم   | نص المنشور |
| `service`   | أحدهما | الشبكة: instagram / twitter / linkedin / facebook … |
| `channel_id`| أحدهما | معرّف القناة الصريح (يتجاوز service) |
| `mode`      | لا    | queue (افتراضي) / draft / schedule |
| `due_at`    | مع schedule | "YYYY-MM-DD HH:MM" بتوقيت السعودية |
| `image_url` | لا    | رابط عام للصورة (Buffer لا يقبل الرفع المباشر) |

المفتاح يُقرأ من Secret باسم `BUFFER_API_KEY` (انظر docs/buffer-setup.md).
