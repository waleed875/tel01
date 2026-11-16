# Engineering Tutor — بوت الهندسة المحلي

معلّم تلغرام باللغة العربية لأربعة مجالات: **الرياضيات، الفيزياء، هندسة البرمجيات، هندسة الإلكترونيات**. يستخدم **PostgreSQL** لحفظ الطلاب والمحادثات والتقدم، و**Ollama** لتشغيل نموذج لغة محلي على جهازك أو خادمك. لا يستخدم OpenAI API أو مفاتيح ذكاء اصطناعي سحابية.

## متطلبات التشغيل

- Docker Engine + Docker Compose Plugin (أو Docker Desktop).
- مساحة كافية للنموذج والبيانات (عدة غيغابايت)، وذاكرة مناسبة. النموذج الافتراضي **qwen2.5:3b** يعمل على CPU ولكن قد يكون بطيئًا. يمكن اختيار نموذج محلي آخر بتغيير OLLAMA_MODEL؛ ينبغي التحقق من توافقه مع الذاكرة واللغة العربية.
- اتصال إنترنت لتنزيل صور Docker والنموذج أول مرة، وللاتصال بخوادم Telegram أثناء التشغيل.
- رمز بوت من [@BotFather](https://t.me/BotFather). لا تضعه في GitHub.

## تشغيل Docker Compose

على Linux أو macOS:

```bash
git clone https://github.com/waleed875/tel01.git
cd tel01/mathematics-and-physics
cp .env.example .env
```

على Windows PowerShell:

```powershell
git clone https://github.com/waleed875/tel01.git
cd tel01/mathematics-and-physics
Copy-Item .env.example .env
notepad .env
```

**إن كنت تستخدم فرع التطوير قبل دمجه في main** نفّذ بعد الاستنساخ:

```bash
git checkout feature/local-engineering-tutor
```

ضع داخل `.env` الرمز الحقيقي `TELEGRAM_BOT_TOKEN` وكلمة مرور PostgreSQL طويلة وعشوائية في `POSTGRES_PASSWORD`، ولا تترك قيم المثال.

```bash
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs -f tutor
```

عند أول تشغيل ينزل `model-init` نموذج Ollama وقد يستغرق هذا حسب سرعة الإنترنت وحجم النموذج. التشغيل التالي يستخدم النموذج المخزن في volume `ollama_models`. بعد تشغيل الحاويات افتح بوت تلغرام وأرسل `/start`.

لم نكشف منفذ قاعدة البيانات ولا منفذ Ollama على الإنترنت. البوت يستخدم **long polling** ولا يحتاج إعداد webhook أو HTTPS أو فتح منافذ واردة.

## الخدمات

- `postgres`: PostgreSQL 17، volume باسم `postgres_data` يحتفظ بالمعلومات عند إعادة إنشاء الحاويات.
- `ollama`: خدمة استدلال نموذج اللغة محليًا، volume باسم `ollama_models`.
- `model-init`: تنتظر Ollama وتنزّل النموذج المحدد ثم تنتهي.
- `tutor`: بوت Telegram من aiogram؛ يتصل بقاعدة البيانات والنموذج داخل شبكة Docker.

### تحديث التطبيق أو إعادة تشغيله

```bash
docker compose up --build -d
docker compose logs -f tutor
```

لإيقاف الخدمات دون مسح البيانات:

```bash
docker compose down
```

**تحذير:** لا تستخدم `docker compose down -v` ما لم تكن تريد حذف بيانات PostgreSQL والنموذج المحمل.

### نسخ قاعدة البيانات احتياطيًا

```bash
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > tutor_backup.sql
```

احتفظ بالنسخة الاحتياطية في مكان آمن. استعادة النسخة تحتاج قاعدة مناسبة وأمر `psql` بعد التأكد من سلامة النسخة.

## الاستخدام

- `/start` القائمة الرئيسية
- `/math` رياضيات
- `/physics` فيزياء
- `/software` هندسة البرمجيات
- `/electronics` هندسة الإلكترونيات
- `/level` المستوى
- `/lesson` شرح درس ملائم للمجال أو `/lesson قوانين كيرشوف`
- `/quiz` أسئلة ثابتة في الرياضيات والفيزياء (بنك من 24 سؤالًا). في المجالين الهندسيين اطلب من النموذج المحلي سؤالًا في المحادثة، لكن تقييمه ليس مربوطًا بإحصاءات الاختبارات الثابتة بعد.
- `/progress` نتائج الاختبارات
- `/new` بدء محادثة جديدة
- `/delete_data` حذف البيانات الشخصية المخزنة

## إضافة المعرفة

الملفات النصية داخل `knowledge/*.md` تحتوي مقتطفات تعليمية مختصرة. يستخدم `knowledge.py` بحثًا بسيطًا بالكلمات لجلب مقتطفات ذات صلة وإرسالها مع السؤال إلى النموذج المحلي. هذه **ليست عملية تدريب على الأوزان**؛ إنها قاعدة معرفة بسيطة قابلة للتطوير لاحقًا إلى RAG باستخدام pgvector ومصادر مرجعية موثقة.

النموذج الافتراضي **نصي فقط**؛ لا يدعم حل مسائل مصورة. يمكن لاحقًا استبداله بنموذج رؤية محلي بعد تعديل معالجة الصور. البوت لم يُختبر بعد ضمن Docker تشغيلًا فعليًا بوجود توكن تلغرام.

## الخصوصية والأمان

- لا تنشر `.env` أو أي رمز تلغرام/كلمة مرور.
- تبقى استفسارات الذكاء الاصطناعي داخل Ollama المحلي، لكن رسائل Telegram تمر عبر خدمة Telegram نفسها.
- PostgreSQL وOllama لا يعرضان منافذ للعامة؛ لا تنشرهما دون حماية.
- بيانات المستخدمين وسجل المحادثات موجودة في `postgres_data`؛ أجر نسخًا احتياطيًا آمنًا.
- يُنشئ التطبيق جداول PostgreSQL الأساسية تلقائيًا؛ الانتقال لاحقًا إلى إنتاج متعدد الإصدارات يستلزم نظام migrations.
- نموذج اللغة قد يخطئ، خاصة في الحسابات أو الهندسة الكهربائية؛ تحقق من الحلول قبل التنفيذ.
- إصدار `run_windows.bat` السابق ليس طريقة النشر المعتمدة في هذا الفرع؛ استخدم Docker Compose.
