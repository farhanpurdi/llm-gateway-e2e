# LLM Gateway E2E

Suite regresi untuk gateway LiteLLM perusahaan. Semua komunikasi gateway
memakai `tests/client.py`; provisioning dan cleanup berada di
`tests/conftest.py`; assertion perilaku berada di `tests/test_*.py`.

Dokumentasi project: [README docs](../llm-gateway-docs/README.md),
[status acceptance Phase1](../llm-gateway-docs/architecture/phase-1.md), dan
[panduan melanjutkan untuk AI](../llm-gateway-docs/handover/AI_CONTINUATION.md).

## Persiapan

Jalankan perintah dari direktori `llm-gateway-e2e`, dengan environment Python
yang memiliki dependency `requirements.lock` dan ShellCheck untuk validasi CI.
CI memasang pin versi/hash dengan `python -m pip install --require-hashes -r requirements.lock`;
`requirements.txt` tetap menyatakan range kompatibilitas.
Pada workspace ini, virtual environment bersama dapat diaktifkan dengan:

```bash
source ../.venv/bin/activate
```

Runner smoke/live memuat `.env` dari repo saudara `llm-gateway-infra`.
Gunakan `E2E_ENV_FILE` untuk memilih file environment lain. Jangan menyalin
secret ke repository, output tes, atau laporan.

Gateway tests membutuhkan `LITELLM_BASE_URL` dan `LITELLM_MASTER_KEY` untuk
provisioning identitas disposable. Inference memakai virtual key identitas
tes. Alias default `company-fast` / `company-coding` dapat diatur melalui
`E2E_FAST_MODEL` / `E2E_CODING_MODEL`.

## Runner dan checkpoint H9E

| Perintah | Cakupan | Akses layanan |
|---|---|---|
| `./scripts/ci/validate.sh` | 8 tahap validasi, collection, dan tes unit | Tanpa gateway/provider |
| `./scripts/run-unit.sh` | 97 kasus regresi offline (`unit`) | HTTP diblokir fixture unit |
| `./scripts/run-live.sh tests/test_lifecycle.py` | 2 tes lifecycle H9A–H9D | Gateway dan inference berbayar |
| `./scripts/run-smoke.sh` | 5 tes (`not live and not unit`) | Gateway, termasuk policy pilot dan onboarding operator |
| `./scripts/run-native.sh` | 13 skenario error/retry SDK/router/handler native | Proses Python pada container existing, tanpa providerIO |
| `./scripts/run-live.sh` | 30 kasus live biasa termasuk agent, guard mock dan rotasi key | Gateway dan inference berbayar; perlu sibling repos/CLI OpenCode existing; outage dikecualikan |
| `./scripts/run-outage.sh --confirm-existing-maintenance` | 2 kasus outage PostgreSQL/Redis | Maintenance existing4000; stop/start dependency yang sama, recovery+cleanup |
| `./scripts/run-all.sh` | Unit → smoke → native → live biasa; berhenti jika gagal | Tidak menjalankan maintenance outage |
| `./scripts/run-all.sh --include-outage` | Seluruh rangkaian di atas lalu outage | Full verification; koordinasikan maintenance, jangan jalankan paralel |

Checkpoint incremental:

1. Jalankan `./scripts/ci/validate.sh`. Delapan tahap harus PASS.
2. Jalankan `./scripts/run-live.sh tests/test_lifecycle.py`. Kedua tes dan
   teardown harus PASS.
3. Jalankan `./scripts/run-smoke.sh`, lalu `./scripts/run-live.sh` untuk
   memastikan lifecycle tidak merusak regression suite lainnya.
4. Catat hasil aktual dalam handoff. Collection saja bukan hasil live PASS.

Collection P1-FINAL17Oktober: **134 kasus pytest** dari51fungsi tes:
97unit,5smoke,30live biasa dan2outage. Probe native13skenario terpisah daripytest.
Collection adalah inventaris, bukan bukti eksekusiPASS; hasil aktual di
[laporan akhir aktif](../llm-gateway-docs/reports/PHASE1_FINAL_CROSSCHECK_REPORT.md).
Snapshot P1-11/P1-12:106kasus(79/5/22). Snapshot P1-09/P1-10:84kasus(61/4/19);
snapshot H10 sebelumnya 37 kasus (22/3/12).
Parameterisasi menyebabkan jumlah kasus lebih besar daripada jumlah fungsi.

Untuk diagnosis, runner unit/live menerima argumen pytest tambahan, misalnya:

```bash
./scripts/run-unit.sh --tb=short
./scripts/run-live.sh tests/test_lifecycle.py --tb=short
```

Jalankan tes gateway secara serial. Jangan menambah parallel execution untuk
tes enforcement tanpa mengevaluasi isolasi rate limit dan budget.

## Perlindungan regresi

`scripts/ci/validate-suite.py` mewajibkan 25 fungsi tes gateway, termasuk:

- `test_multiple_user_keys_work_before_offboarding`
- `test_user_offboarding_blocks_all_keys`

Tes unit menjalankan validator pada salinan sementara, menghilangkan setiap
fungsi lifecycle secara bergantian, dan memastikan validator gagal. File
asli tidak diubah. Validasi PR juga mengeksekusi tes unit; tidak hanya collection.
Enam fungsi P1-09 tambahan juga dilindungi tes penghapusan pada salinan sementara.
Dua fungsi onboarding/agent OpenCode juga wajib dan memiliki tes penghapusan.
Guard mock, outage dependency dan rotasi key juga wajib, dengan tes penghapusan.

## Checkpoint P1-FINAL: failure dan operasi

Parameter mock berbahaya ditolak400 pada gateway nyata, lalu credential sama diuji
inference normal. Jangan mengaktifkan pengaturan dangerous mock untuk melewati guard.
Probe native mensimulasikan429/500/timeout408 dan retry2(3attempt) dalam SDK/router/
handler terpasang; bukan memicu error provider nyata.

Maintenance runner dibatasi URL lokal4000 dan dua nama dependency existing. Context
manager serta trap shell memulihkan layanan; key/team disposable diblokir dan audit
dipertahankan. PGdown pada konfigurasi ini menolak warm/cold503; Redis belum dipakai
sebagai nativecache sehingga inference tetap200 dan negativeauth/ACL/budget tetap
ditolak. Hasil tersebut bukan bukti limit terdistribusi/concurrency/HA.

Rotasi menerbitkan key pengganti dengan user/team/scope sama, memverifikasi sebelum
cutover, memblokir keylama, lalu memeriksa deny/new inference/audit/spend. Counter dan
rowspend asinkron ditunggu terpisah. Fixturecleanup terdaftar sebelum setup selesai;
HTTPtransport error, responsebody gagal dan credential/header repr disensor.

## Checkpoint P1-11/P1-12

OpenCode existing **2.0.18** diperlukan untuk tes agent. Fixture memanggil script
operator `onboard-developer.sh` asli dengan policy `pilot`, lalu memberikan hanya
virtual key developer kepada CLI. Config berasal dari template sibling; config
pribadi tidak ditimpa. Session/data CLI berada pada direktori sementara fixture.

```bash
./scripts/run-smoke.sh
./scripts/test-opencode.sh --tb=short -s
./scripts/run-live.sh tests/test_opencode.py tests/test_inference.py -k 'opencode_agent or streaming or tool_calling' --tb=short -s
```

Perintah terakhir menjalankan 6 kasus live, bukan seluruh 22 kasus. Kedua alias
membaca `calculator.py`, memperbaiki fungsi, menjalankan `python3 verify.py`, lalu
menyebut receipt acak dari hasil tool. Assertion memeriksa urutan tool, receipt,
verifier tetap utuh, kode hasil lulus verifikasi independen, dan request/spend milik
key/user/team/alias/upstream yang tepat. Streaming SSE dan structured tool call API
juga diperiksa untuk kedua alias. Fixture membatasi 8 langkah dan 768 token output
per request; shell hanya mengizinkan perintah verifier dan akses luar direktori
ditolak. Ini izin fixture tes, bukan perubahan permission client perusahaan.

Tes unit menolak jawaban sukses tanpa bukti tool/result, urutan salah, command salah,
error CLI atau receipt salah. Credential/raw CLI output tidak dicetak. Cleanup
menemukan seluruh key user fixture, memblokir dan memeriksa ulang key/team tanpa
menghapus histori. [Laporan dan kode](../llm-gateway-docs/reports/P1_11_P1_12_OPENCODE_REPORT.md).

## Checkpoint P1-09/P1-10

Gunakan policy sibling `llm-gateway-config/policies/teams/pilot.yaml` yang dipilih
user: kedua alias, team US$10, anggota US$2, RPM30/TPM100000. PyYAML dibutuhkan untuk
membaca YAML dan sudah tersedia pada environment workspace existing.

```bash
./scripts/run-smoke.sh --tb=short
./scripts/run-live.sh tests/test_spend.py tests/test_pilot_limits.py tests/test_limits.py --tb=short -s
```

Tes live terfokus ini mempunyai 11 kasus; bukan seluruh 19 kasus live. Factory membuat
dua anggota/empat key pada team disposable; override kecil hanya dipakai untuk
enforcement, file policy asli tetap utuh. Cleanup memverifikasi seluruh key dan team
terblokir serta mempertahankan histori. Jalankan tes secara serial pada existing4000.

`30d` pada LiteLLM1.104.0 memakai awal bulan berikutnya UTC, bukan tepat 30 hari sejak
provisioning. Scheduler reset existing berjalan sekitar setiap 10 menit. Tes reset
anggota memakai durasi fixture5s dan timeout default660s; `E2E_BUDGET_RESET_TIMEOUT`
dapat mengatur waktu tunggu tes, tanpa mengubah interval/scheduler gateway.

Tes biaya memeriksa ID respons provider, token, user/key/member/team, logical alias,
upstream dan harga standar OpenAI dalam `tests/accounting.py`. Oracle adalah snapshot
13 Oktober 2026; tidak mengubah harga runtime. Harga/tier/workload berbeda memerlukan
verifikasi baru. Model-info/raw error body/credential repr disaring pada helper.
Lihat [laporan, kode dan batas bukti](../llm-gateway-docs/reports/P1_09_P1_10_LIMITS_COST_REPORT.md).

Regresi offline memeriksa:

- Seluruh halaman key ditemukan sebelum pemblokiran dimulai.
- Data user lain, token duplikat/kosong, halaman salah, perubahan jumlah key,
  dan discovery tidak lengkap menghentikan operasi sebelum key diblokir.
- Kegagalan HTTP, exception, identitas salah, atau status block yang belum
  terkonfirmasi tetap mencoba key berikutnya lalu melaporkan kegagalan parsial.
- Assertion H9D yang sebenarnya menolak histori yang hilang, atribusi berubah,
  dan nilai spend berubah. Respons API disimulasikan tanpa HTTP.

## Cleanup dan batas operasional offboarding

Fixture lifecycle menggunakan satu user/team disposable dengan dua key untuk
`developer-laptop` dan `developer-ci`. Cleanup memblokir key dan team; record
tidak dihapus agar spend serta histori tetap dapat diaudit. Kegagalan cleanup
membuat teardown gagal. Jangan menjalankan cleanup fixture terhadap shared team.

`offboard_user_keys()` memblokir snapshot key dari discovery. Ia tidak mengunci
provisioning atau melarang penerbitan key baru. Untuk penggunaan operasional:

1. Hentikan atau serialisasikan provisioning key untuk user target selama
   offboarding, termasuk jalur yang dapat menerbitkan key baru.
2. Temukan dan blokir key user; kegagalan parsial harus ditangani, bukan dianggap
   offboarding berhasil.
3. Verifikasi ulang status key dan penolakan credential sebelum menyatakan
   selesai. Pembacaan ulang tanpa koordinasi provisioning tidak menutup race.
4. Pertahankan user/team/key dan histori; jangan memblokir shared team untuk
   mengatasi offboarding satu user.

H9 menguji kondisi tanpa provisioning bersamaan. Histori H9D memakai satu
halaman dengan pemeriksaan jumlah record agar truncation tidak diabaikan;
polling spend/histori masing-masing memiliki jendela 20 detik.

## CI

- `Validate E2E Suite`: validasi statis, collection, dan regresi unit tanpa secret.
- Workflow live staging lama dihapus atas persetujuan pengguna **O-08,17Oktober2026**.
  GitHub menjalankan validate/security offline; tidak ada joblive palsu yang hijau
  dari collection/upload. Hosted runner tidak mengakses laptop4000.
- Live menjadi gate manual pada Docker existing4000:jalankan `run-all.sh --include-outage`
  secara serial, simpan sourceSHA/hash, imageID/digest, output+exit0 dan bukti
  cleanup/recovery. Reviewer memeriksa kecocokan bukti dengan candidatePR/release.
- Lihat [gate lokal](../llm-gateway-docs/operations/local-release-gate.md) dan
  [keputusan](../llm-gateway-docs/reports/PHASE1_RELEASE_DECISIONS.md).
  Persetujuan ini bukan CI candidatePASS, deploy/server approval atau penerimaan CVE.
