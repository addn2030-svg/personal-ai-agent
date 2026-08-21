#!/usr/bin/env bash
# دفع آمن إلى GitHub مع نسخة احتياطية من المحتوى القديم إن وجد.
# الاستخدام:  GITHUB_TOKEN=xxx bash scripts/push_to_github.sh
# لا يُخزَّن الرمز في أي ملف — ويُحذف من إعدادات المستودع بعد الدفع.
set -e
cd "$(dirname "$0")/.."
TOKEN="${GITHUB_TOKEN:?ضع الرمز في متغير البيئة GITHUB_TOKEN}"
REPO="${REPO:-addn2030-svg/personal-ai-agent}"

git remote remove origin 2>/dev/null || true
git remote add origin "https://x-access-token:${TOKEN}@github.com/${REPO}.git"

echo "⏳ فحص المستودع البعيد..."
if git ls-remote --heads origin main 2>/dev/null | grep -q "refs/heads/main"; then
  echo "📦 يوجد محتوى قديم — أُنشئ نسخة احتياطية في backup/pre-ai-os..."
  git fetch origin main
  git push origin origin/main:refs/heads/backup/pre-ai-os --force
  echo "🚀 استبدال main بالنظام الجديد..."
  git push -u origin main --force
else
  echo "🚀 المستودع فارغ — دفع أول..."
  git push -u origin main
fi

# تنظيف: إزالة الرمز من إعدادات git بعد الدفع
git remote set-url origin "https://github.com/${REPO}.git"
echo "✅ تم الرفع بنجاح — المحتوى القديم (إن وجد) في فرع backup/pre-ai-os"
echo "🔐 لا تنسَ إبطال الرمز من GitHub بعد التأكد"
