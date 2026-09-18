# Gift Lead Gen — keyword table

Crawl = bắt rộng theo cluster. Classify = chỉ giữ bài có **gift context + demand/buy intent**.

Process: `gift_leads` · Source: `src/social_listening/gift_leads.py`

## Quy tắc

| Tầng | Việc |
|---|---|
| Crawl keywords | Gift intent + Bulk order + Product (+ priority phrases) |
| Không crawl đơn | `công ty`, `doanh nghiệp`, `khách hàng`… (dùng classify boost) |
| Lead | Có quà/hộp/giỏ/set **và** cần/đặt/mua/báo giá/số lượng lớn… |
| Không phải lead | `"Quà Tết năm nay đẹp quá ❤️"` |

## Bảng keyword (dev copy)

| keyword | cluster | priority | match | ví dụ bài được bắt |
|---|---|---|---|---|
| cần quà Tết cho nhân viên | priority_phrase | 1 | contains | Công ty cần quà Tết cho nhân viên |
| công ty cần đặt quà cuối năm | priority_phrase | 1 | contains | Công ty cần đặt quà cuối năm |
| tìm hộp quà doanh nghiệp | priority_phrase | 1 | contains | Tìm hộp quà doanh nghiệp báo giá |
| đặt quà số lượng lớn | priority_phrase | 1 | contains | Đặt quà số lượng lớn cho 200 NV |
| cần mua quà tặng khách hàng | priority_phrase | 1 | contains | Cần mua quà tặng khách hàng |
| tặng quà | gift_intent | 2 | contains | Cần tặng quà đối tác cuối năm |
| mua quà tặng | gift_intent | 2 | contains | Muốn mua quà tặng khách hàng |
| quà tặng | gift_intent | 2 | contains | Báo giá quà tặng doanh nghiệp |
| quà doanh nghiệp | gift_intent | 2 | contains | Tìm quà doanh nghiệp số lượng lớn |
| quà công ty | gift_intent | 2 | contains | Công ty đặt quà công ty biếu KH |
| quà khách hàng | gift_intent | 2 | contains | Cần quà khách hàng cuối năm |
| quà đối tác | gift_intent | 2 | contains | Đặt quà đối tác, xin báo giá |
| quà nhân viên | gift_intent | 2 | contains | Cần quà nhân viên dịp Tết |
| quà cuối năm | gift_intent | 2 | contains | Công ty cần quà cuối năm |
| quà Tết | gift_intent | 2 | contains | Cần đặt quà Tết cho nhân viên |
| quà Tết doanh nghiệp | gift_intent | 2 | contains | Quà Tết doanh nghiệp báo giá |
| quà tri ân | gift_intent | 2 | contains | Đặt quà tri ân khách hàng |
| quà biếu | gift_intent | 2 | contains | Cần quà biếu đối tác |
| quà biếu khách hàng | gift_intent | 2 | contains | Đặt quà biếu khách hàng |
| quà biếu đối tác | gift_intent | 2 | contains | Cần quà biếu đối tác |
| quà sự kiện | gift_intent | 2 | contains | Đặt quà sự kiện công ty |
| mua số lượng lớn | bulk_order | 2 | contains | Mua số lượng lớn hộp quà |
| đặt số lượng lớn | bulk_order | 2 | contains | Đặt số lượng lớn set quà |
| đặt quà số lượng lớn | bulk_order | 2 | contains | Đặt quà số lượng lớn |
| cần số lượng lớn | bulk_order | 2 | contains | Cần số lượng lớn quà tặng |
| đặt nhiều | bulk_order | 2 | contains | Đặt nhiều hộp quà biếu |
| mua nhiều | bulk_order | 2 | contains | Mua nhiều giỏ quà Tết |
| tặng nhiều người | bulk_order | 2 | contains | Cần tặng nhiều người trong cty |
| tặng khách hàng | bulk_order | 2 | contains | Cần quà tặng khách hàng |
| tặng đối tác | bulk_order | 2 | contains | Cần quà tặng đối tác |
| tặng nhân viên | bulk_order | 2 | contains | Cần quà tặng nhân viên |
| hộp quà | product | 3 | contains | Báo giá hộp quà doanh nghiệp |
| hộp quà tặng | product | 3 | contains | Tìm hộp quà tặng KH |
| hộp quà doanh nghiệp | product | 3 | contains | Hộp quà doanh nghiệp đặt sỉ |
| hộp quà Tết | product | 3 | contains | Đặt hộp quà Tết số lượng lớn |
| set quà | product | 3 | contains | Báo giá set quà biếu |
| set quà tặng | product | 3 | contains | Cần set quà tặng đối tác |
| combo quà | product | 3 | contains | Đặt combo quà cuối năm |
| giỏ quà | product | 3 | contains | Cần giỏ quà biếu sếp |
| giỏ quà Tết | product | 3 | contains | Đặt giỏ quà Tết cho NV |
| giỏ quà doanh nghiệp | product | 3 | contains | Giỏ quà doanh nghiệp báo giá |

## Intent tags (sau classify)

| intent_tag | Khi nào |
|---|---|
| `corporate_gift` | Có DN/công ty/đối tác/NV/KH |
| `year_end_gift` | Quà cuối năm / Tết |
| `bulk_order` | Số lượng lớn / đặt nhiều |
| `buy_gift` | Demand mua/đặt quà chung |

## Seed

```bash
PYTHONPATH=src python3 scripts/mkt/seed_gift_leads_config.py --force
```
