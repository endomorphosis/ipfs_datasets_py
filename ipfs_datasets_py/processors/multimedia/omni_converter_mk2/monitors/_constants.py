class Constants:

    class SecurityMonitor:

        DANGEROUS_PATTERNS_REGEX = [ # TODO Make comprehensive
            r"<script.*?>.*?</script>",
            r"javascript:",
            r"vbscript:",
            r"<iframe.*?>.*?</iframe>",
            r"eval\s*\(",
            r"document\.write\s*\(",
            r"<object.*?>.*?</object>",
            r"<embed.*?>.*?</embed>",
            r"<applet.*?>.*?</applet>",
            r"<form.*?>.*?</form>"
        ]

        EXECUTABLE_EXTENSIONS = [ # TODO Make comprehensive
            ".exe", ".com", ".bat", ".cmd", ".sh", 
            ".ps1", ".vbs", ".js", ".jar", ".dll", 
            ".so"
        ]

        FILE_SIZE_LIMITS_IN_BYTES = { # TODO This should be in a config file
            "default": 100 * 1024 * 1024,  # 100 MB general limit
            "text": 10 * 1024 * 1024,      # 10 MB for text files
            "image": 50 * 1024 * 1024,     # 50 MB for images
            "audio": 100 * 1024 * 1024,    # 100 MB for audio
            "video": 500 * 1024 * 1024,    # 500 MB for video
            "application": 100 * 1024 * 1024,  # 100 MB for applications
        }

        FORMAT_NAMES = {
            "text": ["html", "xml", "plain", "csv", "calendar"],
            "image": ["jpeg", "png", "gif", "webp", "svg"],
            "audio": ["mp3", "wav", "ogg", "flac", "aac"],
            "video": ["mp4", "webm", "avi", "mkv", "mov"],
            "application": ["pdf", "json", "docx", "xlsx", "zip"]
        }

        PII_DETECTION_REGEX = [ # TODO This should be in a config file
            # Email addresses
            (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL REDACTED]'),
            # Phone numbers (various formats)
            (r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE REDACTED]'),
            # Social Security Numbers
            (r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b', '[SSN REDACTED]'),
            # Credit card numbers (comprehensive validation)
            (r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3[0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b', '[CREDIT CARD REDACTED]'),
            # Credit card numbers with separators (spaces, hyphens, dots)
            (r'\b(?:4[0-9]{3}[-.\s]?[0-9]{4}[-.\s]?[0-9]{4}[-.\s]?[0-9]{4}(?:[-.\s]?[0-9]{3})?|5[1-5][0-9]{2}[-.\s]?[0-9]{4}[-.\s]?[0-9]{4}[-.\s]?[0-9]{4}|3[47][0-9]{2}[-.\s]?[0-9]{6}[-.\s]?[0-9]{5}|3[0-9]{3}[-.\s]?[0-9]{6}[-.\s]?[0-9]{4}|6(?:011|5[0-9]{2})[-.\s]?[0-9]{4}[-.\s]?[0-9]{4}[-.\s]?[0-9]{4})\b', '[CREDIT CARD REDACTED]'),
            # Dates of birth (various formats)
            (r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', '[DATE REDACTED]'),
            # IP addresses
            (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP REDACTED]'),
            # URLs (simplified)
            (r'https?://[^\s<>"\']+', '[URL REDACTED]')
        ]

        REMOVE_ACTIVE_CONTENT_REGEX = [
            r"<iframe.*?>.*?</iframe>",
            r"<object.*?>.*?</object>",
            r"<embed.*?>.*?</embed>",
            r"<applet.*?>.*?</applet>",
            r"<form.*?>.*?</form>"
        ]

        REMOVE_SCRIPTS_REGEX = [
            r"<script.*?>.*?</script>",
            r"javascript:[^\s\"'<>]*",
            r"vbscript:[^\s\"'<>]*",
            r"eval\s*\([^)]*\)"
        ]

        SECURITY_RULES = { # TODO This should be in a config file
            "reject_executable": True,
            "reject_encrypted": True,
            "reject_password_protected": True,
            "max_compression_ratio": 100,  # Reject files with compression ratio > 100:1
            "sanitize_content": True,
            "remove_scripts": True,
            "remove_active_content": True,
            "remove_personal_data": True,
            "remove_metadata": False,  # We generally want to keep metadata
        }

        SENSITIVE_KEYS = [ 
            # NOTE The languages present here are the most common on the internet.
            # Personal Information - English
            "author", "creator", "producer", "owner", "company", "email", 
            "phone", "address", "gps", "location", "username", "user",
            "first_name", "last_name", "full_name", "name", "surname",
            "birth_date", "birthday", "age", "ssn", "social_security",
            "passport", "license", "id_number", "employee_id",
            
            # Personal Information - Spanish
            "autor", "creador", "productor", "propietario", "empresa", "correo",
            "telefono", "direccion", "ubicacion", "nombre_usuario", "usuario",
            "nombre", "apellido", "nombre_completo", "apellidos",
            "fecha_nacimiento", "cumpleanos", "edad", "seguridad_social",
            "pasaporte", "licencia", "numero_id", "id_empleado",
            
            # Personal Information - German
            "autor", "ersteller", "produzent", "eigentumer", "unternehmen",
            "telefon", "adresse", "standort", "benutzername", "benutzer",
            "vorname", "nachname", "vollname", "familienname",
            "geburtsdatum", "geburtstag", "alter", "sozialversicherung",
            "reisepass", "lizenz", "personalausweis", "mitarbeiter_id",
            
            # Personal Information - French
            "auteur", "createur", "producteur", "proprietaire", "entreprise",
            "telephone", "adresse", "localisation", "nom_utilisateur", "utilisateur",
            "prenom", "nom", "nom_complet", "nom_famille",
            "date_naissance", "anniversaire", "age", "securite_sociale",
            "passeport", "licence", "numero_id", "id_employe",
            
            # Personal Information - Japanese
            "著者", "作成者", "制作者", "所有者", "会社", "メール",
            "電話", "住所", "位置", "ユーザー名", "ユーザー",
            "名前", "姓", "フルネーム", "苗字",
            "生年月日", "誕生日", "年齢", "社会保障",
            "パスポート", "免許", "ID番号", "従業員ID",
            
            # Personal Information - Portuguese
            "autor", "criador", "produtor", "proprietario", "empresa",
            "telefone", "endereco", "localizacao", "nome_usuario", "usuario",
            "primeiro_nome", "sobrenome", "nome_completo", "apelido",
            "data_nascimento", "aniversario", "idade", "seguridade_social",
            "passaporte", "licenca", "numero_id", "id_funcionario",
            
            # Personal Information - Russian
            "автор", "создатель", "производитель", "владелец", "компания",
            "телефон", "адрес", "местоположение", "имя_пользователя", "пользователь",
            "имя", "фамилия", "полное_имя", "отчество",
            "дата_рождения", "день_рождения", "возраст", "социальное_страхование",
            "паспорт", "лицензия", "номер_удостоверения", "id_сотрудника",
            
            # Personal Information - Italian
            "autore", "creatore", "produttore", "proprietario", "azienda",
            "telefono", "indirizzo", "posizione", "nome_utente", "utente",
            "nome", "cognome", "nome_completo", "famiglia",
            "data_nascita", "compleanno", "eta", "sicurezza_sociale",
            "passaporto", "licenza", "numero_id", "id_dipendente",
            
            # Personal Information - Dutch
            "auteur", "maker", "producent", "eigenaar", "bedrijf",
            "telefoon", "adres", "locatie", "gebruikersnaam", "gebruiker",
            "voornaam", "achternaam", "volledige_naam", "familienaam",
            "geboortedatum", "verjaardag", "leeftijd", "sociale_zekerheid",
            "paspoort", "licentie", "id_nummer", "werknemer_id",
            
            # Personal Information - Polish
            "autor", "tworca", "producent", "wlasciciel", "firma",
            "telefon", "adres", "lokalizacja", "nazwa_uzytkownika", "uzytkownik",
            "imie", "nazwisko", "pelne_imie", "rodzina",
            "data_urodzenia", "urodziny", "wiek", "ubezpieczenie_spoleczne",
            "paszport", "licencja", "numer_id", "id_pracownika",
            
            # Personal Information - Turkish
            "yazar", "yaratici", "uretici", "sahip", "sirket",
            "telefon", "adres", "konum", "kullanici_adi", "kullanici",
            "ad", "soyad", "tam_ad", "aile_adi",
            "dogum_tarihi", "dogum_gunu", "yas", "sosyal_guvenlik",
            "pasaport", "lisans", "kimlik_numarasi", "calisan_id",
            
            # Personal Information - Persian
            "نویسنده", "سازنده", "تولیدکننده", "مالک", "شرکت",
            "تلفن", "آدرس", "موقعیت", "نام_کاربری", "کاربر",
            "نام", "نام_خانوادگی", "نام_کامل", "فامیل",
            "تاریخ_تولد", "تولد", "سن", "تامین_اجتماعی",
            "پاسپورت", "مجوز", "شماره_شناسه", "شناسه_کارمند",
            
            # Personal Information - Chinese
            "作者", "创建者", "制作人", "所有者", "公司",
            "电话", "地址", "位置", "用户名", "用户",
            "名字", "姓氏", "全名", "家族姓氏",
            "出生日期", "生日", "年龄", "社会保障",
            "护照", "许可证", "身份证号", "员工编号",
            
            # Personal Information - Vietnamese
            "tac_gia", "nguoi_tao", "nha_san_xuat", "chu_so_huu", "cong_ty",
            "dien_thoai", "dia_chi", "vi_tri", "ten_dang_nhap", "nguoi_dung",
            "ten", "ho", "ho_ten", "ten_dem",
            "ngay_sinh", "sinh_nhat", "tuoi", "bao_hiem_xa_hoi",
            "ho_chieu", "giay_phep", "so_id", "id_nhan_vien",
            
            # Personal Information - Indonesian
            "penulis", "pembuat", "produser", "pemilik", "perusahaan",
            "telepon", "alamat", "lokasi", "nama_pengguna", "pengguna",
            "nama_depan", "nama_belakang", "nama_lengkap", "marga",
            "tanggal_lahir", "ulang_tahun", "umur", "jaminan_sosial",
            "paspor", "lisensi", "nomor_id", "id_karyawan",
            
            # Contact Information - English
            "phone_number", "mobile", "cell", "fax", "zip_code", "postal_code",
            "street", "city", "state", "country", "home_address", "work_address",
            "billing_address", "shipping_address", "emergency_contact",
            
            # Contact Information - Spanish
            "numero_telefono", "movil", "celular", "codigo_postal",
            "calle", "ciudad", "estado", "pais", "direccion_casa", "direccion_trabajo",
            "direccion_facturacion", "direccion_envio", "contacto_emergencia",
            
            # Contact Information - German
            "telefonnummer", "handy", "mobiltelefon", "postleitzahl",
            "strasse", "stadt", "bundesland", "land", "hausadresse", "arbeitsadresse",
            "rechnungsadresse", "lieferadresse", "notfallkontakt",
            
            # Contact Information - French
            "numero_telephone", "portable", "cellulaire", "code_postal",
            "rue", "ville", "etat", "pays", "adresse_domicile", "adresse_travail",
            "adresse_facturation", "adresse_livraison", "contact_urgence",
            
            # Contact Information - Japanese
            "電話番号", "携帯", "携帯電話", "郵便番号",
            "通り", "都市", "州", "国", "自宅住所", "勤務先住所",
            "請求先住所", "配送先住所", "緊急連絡先",
            
            # Contact Information - Portuguese
            "numero_telefone", "celular", "movel", "codigo_postal",
            "rua", "cidade", "estado", "pais", "endereco_residencial", "endereco_trabalho",
            "endereco_cobranca", "endereco_entrega", "contato_emergencia",
            
            # Contact Information - Russian
            "номер_телефона", "мобильный", "сотовый", "почтовый_индекс",
            "улица", "город", "область", "страна", "домашний_адрес", "рабочий_адрес",
            "адрес_выставления_счетов", "адрес_доставки", "экстренный_контакт",
            
            # Contact Information - Italian
            "numero_telefono", "cellulare", "mobile", "codice_postale",
            "via", "citta", "regione", "paese", "indirizzo_casa", "indirizzo_lavoro",
            "indirizzo_fatturazione", "indirizzo_spedizione", "contatto_emergenza",
            
            # Contact Information - Dutch
            "telefoonnummer", "mobiel", "gsm", "postcode",
            "straat", "stad", "provincie", "land", "thuisadres", "werkadres",
            "factuuradres", "verzendadres", "noodcontact",
            
            # Contact Information - Polish
            "numer_telefonu", "telefon_komorkowy", "komorkowy", "kod_pocztowy",
            "ulica", "miasto", "wojewodztwo", "kraj", "adres_domowy", "adres_pracy",
            "adres_rozliczeniowy", "adres_wysylki", "kontakt_awaryjny",
            
            # Contact Information - Turkish
            "telefon_numarasi", "cep_telefonu", "mobil", "posta_kodu",
            "sokak", "sehir", "il", "ulke", "ev_adresi", "is_adresi",
            "fatura_adresi", "kargo_adresi", "acil_durum_iletisim",
            
            # Contact Information - Persian
            "شماره_تلفن", "موبایل", "تلفن_همراه", "کد_پستی",
            "خیابان", "شهر", "استان", "کشور", "آدرس_منزل", "آدرس_کار",
            "آدرس_صورتحساب", "آدرس_ارسال", "تماس_اضطراری",
            
            # Contact Information - Chinese
            "电话号码", "手机", "移动电话", "邮政编码",
            "街道", "城市", "省份", "国家", "家庭地址", "工作地址",
            "账单地址", "送货地址", "紧急联系人",
            
            # Contact Information - Vietnamese
            "so_dien_thoai", "di_dong", "dien_thoai_di_dong", "ma_buu_dien",
            "duong", "thanh_pho", "tinh", "quoc_gia", "dia_chi_nha", "dia_chi_lam_viec",
            "dia_chi_hoa_don", "dia_chi_giao_hang", "lien_lac_khan_cap",
            
            # Contact Information - Indonesian
            "nomor_telepon", "ponsel", "handphone", "kode_pos",
            "jalan", "kota", "provinsi", "negara", "alamat_rumah", "alamat_kerja",
            "alamat_tagihan", "alamat_pengiriman", "kontak_darurat",
            
            # Authentication & Security - English
            "password", "passwd", "pwd", "key", "secret", "token", "api_key", 
            "auth", "auth_token", "access_token", "refresh_token", "bearer_token",
            "session_id", "session_key", "csrf_token", "api_secret", "private_key",
            "public_key", "encryption_key", "salt", "hash", "signature",
            "certificate", "cert", "oauth", "oauth_token", "jwt", "apikey",
            
            # Authentication & Security - Spanish
            "contrasena", "clave", "llave", "secreto", "token", "clave_api",
            "autenticacion", "token_auth", "token_acceso", "token_actualizacion", "token_portador",
            "id_sesion", "clave_sesion", "token_csrf", "secreto_api", "clave_privada",
            "clave_publica", "clave_cifrado", "sal", "resumen", "firma",
            "certificado", "cert", "oauth", "token_oauth", "jwt", "claveapi",
            
            # Authentication & Security - German
            "passwort", "kennwort", "schluessel", "geheimnis", "token", "api_schluessel",
            "authentifizierung", "auth_token", "zugangstoken", "aktualisierungstoken", "bearer_token",
            "sitzungs_id", "sitzungsschluessel", "csrf_token", "api_geheimnis", "privater_schluessel",
            "oeffentlicher_schluessel", "verschluesselungsschluessel", "salz", "hash", "signatur",
            "zertifikat", "cert", "oauth", "oauth_token", "jwt", "apischluessel",
            
            # Authentication & Security - French
            "mot_de_passe", "mdp", "cle", "secret", "jeton", "cle_api",
            "authentification", "jeton_auth", "jeton_acces", "jeton_actualisation", "jeton_porteur",
            "id_session", "cle_session", "jeton_csrf", "secret_api", "cle_privee",
            "cle_publique", "cle_chiffrement", "sel", "hachage", "signature",
            "certificat", "cert", "oauth", "jeton_oauth", "jwt", "cleapi",
            
            # Authentication & Security - Japanese
            "パスワード", "暗証番号", "鍵", "秘密", "トークン", "APIキー",
            "認証", "認証トークン", "アクセストークン", "リフレッシュトークン", "ベアラートークン",
            "セッションID", "セッションキー", "CSRFトークン", "API秘密", "秘密鍵",
            "公開鍵", "暗号化キー", "ソルト", "ハッシュ", "署名",
            "証明書", "cert", "oauth", "oauthトークン", "jwt", "apiキー",
            
            # Authentication & Security - Portuguese
            "senha", "palavra_passe", "chave", "segredo", "token", "chave_api",
            "autenticacao", "token_auth", "token_acesso", "token_atualizacao", "token_portador",
            "id_sessao", "chave_sessao", "token_csrf", "segredo_api", "chave_privada",
            "chave_publica", "chave_criptografia", "sal", "hash", "assinatura",
            "certificado", "cert", "oauth", "token_oauth", "jwt", "chaveapi",
            
            # Authentication & Security - Russian
            "пароль", "пароль", "ключ", "секрет", "токен", "ключ_api",
            "аутентификация", "токен_auth", "токен_доступа", "токен_обновления", "носитель_токен",
            "идентификатор_сессии", "ключ_сессии", "токен_csrf", "секрет_api", "закрытый_ключ",
            "открытый_ключ", "ключ_шифрования", "соль", "хеш", "подпись",
            "сертификат", "cert", "oauth", "токен_oauth", "jwt", "ключapi",
            
            # Authentication & Security - Italian
            "password", "parola_d_ordine", "chiave", "segreto", "token", "chiave_api",
            "autenticazione", "token_auth", "token_accesso", "token_aggiornamento", "token_portatore",
            "id_sessione", "chiave_sessione", "token_csrf", "segreto_api", "chiave_privata",
            "chiave_pubblica", "chiave_crittografia", "sale", "hash", "firma",
            "certificato", "cert", "oauth", "token_oauth", "jwt", "chiaveapi",
            
            # Authentication & Security - Dutch
            "wachtwoord", "paswoord", "sleutel", "geheim", "token", "api_sleutel",
            "authenticatie", "auth_token", "toegangstoken", "vernieuwingstoken", "drager_token",
            "sessie_id", "sessiesleutel", "csrf_token", "api_geheim", "prive_sleutel",
            "publieke_sleutel", "versleutelingssleutel", "zout", "hash", "handtekening",
            "certificaat", "cert", "oauth", "oauth_token", "jwt", "apisleutel",
            
            # Authentication & Security - Polish
            "haslo", "haslo", "klucz", "sekret", "token", "klucz_api",
            "uwierzytelnienie", "token_auth", "token_dostepu", "token_odswiezania", "token_nosiciela",
            "id_sesji", "klucz_sesji", "token_csrf", "sekret_api", "klucz_prywatny",
            "klucz_publiczny", "klucz_szyfrowania", "sol", "hash", "podpis",
            "certyfikat", "cert", "oauth", "token_oauth", "jwt", "kluczapi",
            
            # Authentication & Security - Turkish
            "sifre", "parola", "anahtar", "gizli", "token", "api_anahtari",
            "kimlik_dogrulama", "auth_token", "erisim_token", "yenileme_token", "tasiyici_token",
            "oturum_id", "oturum_anahtari", "csrf_token", "api_gizli", "ozel_anahtar",
            "genel_anahtar", "sifreleme_anahtari", "tuz", "hash", "imza",
            "sertifika", "cert", "oauth", "oauth_token", "jwt", "anahtarapi",
            
            # Authentication & Security - Persian
            "رمز_عبور", "گذرواژه", "کلید", "راز", "توکن", "کلید_api",
            "احراز_هویت", "توکن_auth", "توکن_دسترسی", "توکن_تازه‌سازی", "توکن_حامل",
            "شناسه_جلسه", "کلید_جلسه", "توکن_csrf", "راز_api", "کلید_خصوصی",
            "کلید_عمومی", "کلید_رمزنگاری", "نمک", "هش", "امضا",
            "گواهینامه", "cert", "oauth", "توکن_oauth", "jwt", "کلیدapi",
            
            # Authentication & Security - Chinese
            "密码", "口令", "密钥", "秘密", "令牌", "API密钥",
            "认证", "认证令牌", "访问令牌", "刷新令牌", "承载令牌",
            "会话ID", "会话密钥", "CSRF令牌", "API秘密", "私钥",
            "公钥", "加密密钥", "盐", "哈希", "签名",
            "证书", "cert", "oauth", "oauth令牌", "jwt", "api密钥",
            
            # Authentication & Security - Vietnamese
            "mat_khau", "chu_khau", "khoa", "bi_mat", "token", "khoa_api",
            "xac_thuc", "token_auth", "token_truy_cap", "token_lam_moi", "token_mang",
            "id_phien", "khoa_phien", "token_csrf", "bi_mat_api", "khoa_rieng",
            "khoa_cong_khai", "khoa_ma_hoa", "muoi", "bam", "chu_ky",
            "chung_chi", "cert", "oauth", "token_oauth", "jwt", "khoaapi",
            
            # Authentication & Security - Indonesian
            "kata_sandi", "sandi", "kunci", "rahasia", "token", "kunci_api",
            "otentikasi", "token_auth", "token_akses", "token_refresh", "token_pembawa",
            "id_sesi", "kunci_sesi", "token_csrf", "rahasia_api", "kunci_pribadi",
            "kunci_publik", "kunci_enkripsi", "garam", "hash", "tanda_tangan",
            "sertifikat", "cert", "oauth", "token_oauth", "jwt", "kunciapi",
            
            # Financial Information - English
            "credit_card", "card_number", "cvv", "cvc", "expiry", "expiration",
            "bank_account", "routing_number", "iban", "swift", "account_number",
            "payment", "billing", "invoice", "transaction", "balance",
            
            # Financial Information - Spanish
            "tarjeta_credito", "numero_tarjeta", "cvv", "cvc", "vencimiento", "expiracion",
            "cuenta_bancaria", "numero_ruta", "iban", "swift", "numero_cuenta",
            "pago", "facturacion", "factura", "transaccion", "saldo",
            
            # Financial Information - German
            "kreditkarte", "kartennummer", "cvv", "cvc", "ablauf", "verfall",
            "bankkonto", "bankleitzahl", "iban", "swift", "kontonummer",
            "zahlung", "abrechnung", "rechnung", "transaktion", "guthaben",
            
            # Financial Information - French
            "carte_credit", "numero_carte", "cvv", "cvc", "expiration", "echeance",
            "compte_bancaire", "numero_routage", "iban", "swift", "numero_compte",
            "paiement", "facturation", "facture", "transaction", "solde",
            
            # Financial Information - Japanese
            "クレジットカード", "カード番号", "cvv", "cvc", "有効期限", "失効",
            "銀行口座", "ルーティング番号", "iban", "swift", "口座番号",
            "支払い", "請求", "請求書", "取引", "残高",
            
            # Financial Information - Portuguese
            "cartao_credito", "numero_cartao", "cvv", "cvc", "validade", "expiracao",
            "conta_bancaria", "numero_roteamento", "iban", "swift", "numero_conta",
            "pagamento", "faturamento", "fatura", "transacao", "saldo",
            
            # Financial Information - Russian
            "кредитная_карта", "номер_карты", "cvv", "cvc", "истечение", "срок_действия",
            "банковский_счет", "номер_маршрутизации", "iban", "swift", "номер_счета",
            "платеж", "выставление_счетов", "счет", "транзакция", "баланс",
            
            # Financial Information - Italian
            "carta_credito", "numero_carta", "cvv", "cvc", "scadenza", "expiration",
            "conto_bancario", "numero_routing", "iban", "swift", "numero_conto",
            "pagamento", "fatturazione", "fattura", "transazione", "saldo",
            
            # Financial Information - Dutch
            "creditcard", "kaartnummer", "cvv", "cvc", "vervaldatum", "expiratie",
            "bankrekening", "routingnummer", "iban", "swift", "rekeningnummer",
            "betaling", "facturering", "factuur", "transactie", "saldo",
            
            # Financial Information - Polish
            "karta_kredytowa", "numer_karty", "cvv", "cvc", "wygasniecie", "data_waznosci",
            "konto_bankowe", "numer_rozliczeniowy", "iban", "swift", "numer_konta",
            "platnosc", "fakturowanie", "faktura", "transakcja", "saldo",
            
            # Financial Information - Turkish
            "kredi_karti", "kart_numarasi", "cvv", "cvc", "son_kullanma", "gecerlilik",
            "banka_hesabi", "yonlendirme_numarasi", "iban", "swift", "hesap_numarasi",
            "odeme", "faturalama", "fatura", "islem", "bakiye",
            
            # Financial Information - Persian
            "کارت_اعتباری", "شماره_کارت", "cvv", "cvc", "انقضا", "تاریخ_انقضا",
            "حساب_بانکی", "شماره_مسیریابی", "iban", "swift", "شماره_حساب",
            "پرداخت", "صورتحساب", "فاکتور", "تراکنش", "موجودی",
            
            # Financial Information - Chinese
            "信用卡", "卡号", "cvv", "cvc", "到期", "过期时间",
            "银行账户", "路由号", "iban", "swift", "账号",
            "付款", "计费", "发票", "交易", "余额",
            
            # Financial Information - Vietnamese
            "the_tin_dung", "so_the", "cvv", "cvc", "het_han", "ngay_het_han",
            "tai_khoan_ngan_hang", "so_tuyen_duong", "iban", "swift", "so_tai_khoan",
            "thanh_toan", "lap_hoa_don", "hoa_don", "giao_dich", "so_du",
            
            # Financial Information - Indonesian
            "kartu_kredit", "nomor_kartu", "cvv", "cvc", "kedaluwarsa", "masa_berlaku",
            "rekening_bank", "nomor_routing", "iban", "swift", "nomor_rekening",
            "pembayaran", "penagihan", "faktur", "transaksi", "saldo",
            
            # System Information - English
            "server", "host", "hostname", "ip_address", "mac_address",
            "database", "db_password", "db_user", "connection_string",
            "admin", "administrator", "root", "sudo", "system",
            
            # System Information - Spanish
            "servidor", "anfitrion", "nombre_host", "direccion_ip", "direccion_mac",
            "base_datos", "contrasena_bd", "usuario_bd", "cadena_conexion",
            "administrador", "administrador", "raiz", "sudo", "sistema",
            
            # System Information - German
            "server", "host", "hostname", "ip_adresse", "mac_adresse",
            "datenbank", "db_passwort", "db_benutzer", "verbindungsstring",
            "admin", "administrator", "root", "sudo", "system",
            
            # System Information - French
            "serveur", "hote", "nom_hote", "adresse_ip", "adresse_mac",
            "base_donnees", "mot_passe_bd", "utilisateur_bd", "chaine_connexion",
            "admin", "administrateur", "racine", "sudo", "systeme",
            
            # System Information - Japanese
            "サーバー", "ホスト", "ホスト名", "IPアドレス", "MACアドレス",
            "データベース", "DBパスワード", "DBユーザー", "接続文字列",
            "管理者", "アドミニストレーター", "ルート", "sudo", "システム",
            
            # System Information - Portuguese
            "servidor", "host", "nome_host", "endereco_ip", "endereco_mac",
            "banco_dados", "senha_bd", "usuario_bd", "string_conexao",
            "admin", "administrador", "raiz", "sudo", "sistema",
            
            # System Information - Russian
            "сервер", "хост", "имя_хоста", "ip_адрес", "mac_адрес",
            "база_данных", "пароль_бд", "пользователь_бд", "строка_подключения",
            "админ", "администратор", "корень", "sudo", "система",
            
            # System Information - Italian
            "server", "host", "nome_host", "indirizzo_ip", "indirizzo_mac",
            "database", "password_db", "utente_db", "stringa_connessione",
            "admin", "amministratore", "radice", "sudo", "sistema",
            
            # System Information - Dutch
            "server", "host", "hostnaam", "ip_adres", "mac_adres",
            "database", "db_wachtwoord", "db_gebruiker", "verbindingsstring",
            "admin", "beheerder", "root", "sudo", "systeem",
            
            # System Information - Polish
            "serwer", "host", "nazwa_hosta", "adres_ip", "adres_mac",
            "baza_danych", "haslo_bd", "uzytkownik_bd", "string_polaczenia",
            "admin", "administrator", "root", "sudo", "system",
            
            # System Information - Turkish
            "sunucu", "host", "host_adi", "ip_adresi", "mac_adresi",
            "veritabani", "vt_sifre", "vt_kullanici", "baglanti_dizisi",
            "admin", "yonetici", "kok", "sudo", "sistem",
            
            # System Information - Persian
            "سرور", "میزبان", "نام_میزبان", "آدرس_ip", "آدرس_mac",
            "پایگاه_داده", "رمز_عبور_پایگاه", "کاربر_پایگاه", "رشته_اتصال",
            "مدیر", "مدیر_سیستم", "ریشه", "sudo", "سیستم",
            
            # System Information - Chinese
            "服务器", "主机", "主机名", "IP地址", "MAC地址",
            "数据库", "数据库密码", "数据库用户", "连接字符串",
            "管理员", "系统管理员", "根用户", "sudo", "系统",
            
            # System Information - Vietnamese
            "may_chu", "host", "ten_host", "dia_chi_ip", "dia_chi_mac",
            "co_so_du_lieu", "mat_khau_csdl", "nguoi_dung_csdl", "chuoi_ket_noi",
            "admin", "quan_tri_vien", "root", "sudo", "he_thong",
            
            # System Information - Indonesian
            "server", "host", "nama_host", "alamat_ip", "alamat_mac",
            "basis_data", "kata_sandi_db", "pengguna_db", "string_koneksi",
            "admin", "administrator", "root", "sudo", "sistem",
            
            # Metadata Fields - English
            "last_modified_by", "created_by", "edited_by", "reviewed_by",
            "approved_by", "document_id", "revision", "version_history",
            "comments", "notes", "annotations", "tracking_id",
            
            # Metadata Fields - Spanish
            "ultima_modificacion_por", "creado_por", "editado_por", "revisado_por",
            "aprobado_por", "id_documento", "revision", "historial_version",
            "comentarios", "notas", "anotaciones", "id_seguimiento",
            
            # Metadata Fields - German
            "zuletzt_geaendert_von", "erstellt_von", "bearbeitet_von", "geprueft_von",
            "genehmigt_von", "dokument_id", "revision", "versionsverlauf",
            "kommentare", "notizen", "anmerkungen", "verfolgungs_id",
            
            # Metadata Fields - French
            "derniere_modification_par", "cree_par", "edite_par", "examine_par",
            "approuve_par", "id_document", "revision", "historique_version",
            "commentaires", "notes", "annotations", "id_suivi",
            
            # Metadata Fields - Japanese
            "最終変更者", "作成者", "編集者", "レビュー者",
            "承認者", "ドキュメントID", "リビジョン", "バージョン履歴",
            "コメント", "メモ", "注釈", "追跡ID",
            
            # Metadata Fields - Portuguese
            "ultima_modificacao_por", "criado_por", "editado_por", "revisado_por",
            "aprovado_por", "id_documento", "revisao", "historico_versao",
            "comentarios", "notas", "anotacoes", "id_rastreamento",
            
            # Metadata Fields - Russian
            "последнее_изменение_от", "создано_от", "отредактировано_от", "проверено_от",
            "одобрено_от", "идентификатор_документа", "ревизия", "история_версий",
            "комментарии", "заметки", "аннотации", "идентификатор_отслеживания",
            
            # Metadata Fields - Italian
            "ultima_modifica_da", "creato_da", "modificato_da", "revisionato_da",
            "approvato_da", "id_documento", "revisione", "cronologia_versione",
            "commenti", "note", "annotazioni", "id_tracciamento",
            
            # Metadata Fields - Dutch
            "laatst_gewijzigd_door", "gemaakt_door", "bewerkt_door", "beoordeeld_door",
            "goedgekeurd_door", "document_id", "revisie", "versiegeschiedenis",
            "opmerkingen", "notities", "annotaties", "tracking_id",
            
            # Metadata Fields - Polish
            "ostatnio_zmodyfikowane_przez", "utworzone_przez", "edytowane_przez", "sprawdzone_przez",
            "zatwierdzone_przez", "id_dokumentu", "rewizja", "historia_wersji",
            "komentarze", "notatki", "adnotacje", "id_sledzenia",
            
            # Metadata Fields - Turkish
            "son_degistiren", "olusturan", "duzenleyen", "inceleyen",
            "onaylayan", "belge_id", "revizyon", "surum_gecmisi",
            "yorumlar", "notlar", "aciklamalar", "takip_id",
            
            # Metadata Fields - Persian
            "آخرین_تغییر_توسط", "ایجاد_شده_توسط", "ویرایش_شده_توسط", "بررسی_شده_توسط",
            "تایید_شده_توسط", "شناسه_سند", "بازنگری", "تاریخچه_نسخه",
            "نظرات", "یادداشت‌ها", "حاشیه‌نویسی", "شناسه_ردیابی",
            
            # Metadata Fields - Chinese
            "最后修改者", "创建者", "编辑者", "审核者",
            "批准者", "文档ID", "版本", "版本历史",
            "评论", "备注", "注释", "跟踪ID",
            
            # Metadata Fields - Vietnamese
            "sua_doi_cuoi_boi", "tao_boi", "chinh_sua_boi", "xem_xet_boi",
            "phe_duyet_boi", "id_tai_lieu", "ban_sua_doi", "lich_su_phien_ban",
            "binh_luan", "ghi_chu", "chu_thich", "id_theo_doi",
            
            # Metadata Fields - Indonesian
            "terakhir_diubah_oleh", "dibuat_oleh", "diedit_oleh", "ditinjau_oleh",
            "disetujui_oleh", "id_dokumen", "revisi", "riwayat_versi",
            "komentar", "catatan", "anotasi", "id_pelacakan",
            
            # Application Specific - English
            "license_key", "serial_number", "product_key", "activation_code",
            "client_id", "client_secret", "tenant_id", "subscription_id",
            "user_agent", "referrer", "session", "cookie"
            
            # Application Specific - Spanish
            "clave_licencia", "numero_serie", "clave_producto", "codigo_activacion",
            "id_cliente", "secreto_cliente", "id_inquilino", "id_suscripcion",
            "agente_usuario", "referencia", "sesion", "cookie",
            
            # Application Specific - German
            "lizenzschluessel", "seriennummer", "produktschluessel", "aktivierungscode",
            "client_id", "client_geheimnis", "mandanten_id", "abonnement_id",
            "benutzeragent", "verweiser", "sitzung", "cookie",
            
            # Application Specific - French
            "cle_licence", "numero_serie", "cle_produit", "code_activation",
            "id_client", "secret_client", "id_locataire", "id_abonnement",
            "agent_utilisateur", "referent", "session", "cookie",
            
            # Application Specific - Japanese
            "ライセンスキー", "シリアル番号", "プロダクトキー", "アクティベーションコード",
            "クライアントID", "クライアント秘密", "テナントID", "サブスクリプションID",
            "ユーザーエージェント", "リファラー", "セッション", "クッキー",
            
            # Application Specific - Portuguese
            "chave_licenca", "numero_serie", "chave_produto", "codigo_ativacao",
            "id_cliente", "segredo_cliente", "id_inquilino", "id_assinatura",
            "agente_usuario", "referenciador", "sessao", "cookie",
            
            # Application Specific - Russian
            "ключ_лицензии", "серийный_номер", "ключ_продукта", "код_активации",
            "идентификатор_клиента", "секрет_клиента", "идентификатор_арендатора", "идентификатор_подписки",
            "пользовательский_агент", "реферер", "сессия", "cookie",
            
            # Application Specific - Italian
            "chiave_licenza", "numero_serie", "chiave_prodotto", "codice_attivazione",
            "id_cliente", "segreto_cliente", "id_tenant", "id_abbonamento",
            "agente_utente", "referrer", "sessione", "cookie",
            
            # Application Specific - Dutch
            "licentiesleutel", "serienummer", "productsleutel", "activatiecode",
            "client_id", "client_geheim", "huurder_id", "abonnement_id",
            "gebruikersagent", "verwijzer", "sessie", "cookie",
            
            # Application Specific - Polish
            "klucz_licencji", "numer_seryjny", "klucz_produktu", "kod_aktywacji",
            "id_klienta", "sekret_klienta", "id_najemcy", "id_subskrypcji",
            "agent_uzytkownika", "odnosnik", "sesja", "cookie",
            
            # Application Specific - Turkish
            "lisans_anahtari", "seri_numarasi", "urun_anahtari", "aktivasyon_kodu",
            "istemci_id", "istemci_gizli", "kiracı_id", "abonelik_id",
            "kullanici_ajanı", "yonlendiren", "oturum", "cerez",
            
            # Application Specific - Persian
            "کلید_مجوز", "شماره_سری", "کلید_محصول", "کد_فعال‌سازی",
            "شناسه_کلاینت", "راز_کلاینت", "شناسه_مستاجر", "شناسه_اشتراک",
            "عامل_کاربر", "ارجاع‌دهنده", "جلسه", "کوکی",
            
            # Application Specific - Chinese
            "许可证密钥", "序列号", "产品密钥", "激活码",
            "客户端ID", "客户端密钥", "租户ID", "订阅ID",
            "用户代理", "引用页", "会话", "cookie",
            
            # Application Specific - Vietnamese
            "khoa_ban_quyen", "so_seri", "khoa_san_pham", "ma_kich_hoat",
            "id_khach_hang", "bi_mat_khach_hang", "id_thue", "id_dang_ky",
            "dai_ly_nguoi_dung", "nguoi_gioi_thieu", "phien", "cookie",
            
            # Application Specific - Indonesian
            "kunci_lisensi", "nomor_seri", "kunci_produk", "kode_aktivasi",
            "id_klien", "rahasia_klien", "id_penyewa", "id_berlangganan",
            "agen_pengguna", "perujuk", "sesi", "cookie"
        ]

