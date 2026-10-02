import {
  lifetime,
  preEol,
  extValue,
  bootConfig,
  manufacturer,
  supportedModes,
  currentBusRate,
  hexNumber,
  productRevision,
  binaryFlag,
  decodeRegister,
  mmcCsd,
  ocrInfo,
  partitionType,
} from './emmcInfo';
const bytes = (n: number) =>
  `${n.toLocaleString()} B · ${n < 1073741824 ? (n / 1048576).toFixed(2) + ' MiB' : (n / 1073741824).toFixed(3) + ' GiB'} · ${(n / 1e9).toFixed(3)} GB`;
function Group({ title, rows }: { title: string; rows: [string, unknown][] }) {
  return (
    <section className="disk-detail-group">
      <h4>{title}</h4>
      <dl className="details-grid">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v === undefined || v === null || v === '' ? '设备未提供' : String(v)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
export function DiskDetails({
  disk: d,
  ext,
  loading,
  error,
}: {
  disk: any;
  ext: string;
  loading: boolean;
  error: string;
}) {
  const card = d.card_info || {},
    queue = d.queue_info || {},
    block = d.block_info || {},
    parts = d.regions.filter((r: any) => r.region === 'partition'),
    allocated = parts.reduce((n: number, r: any) => n + r.size, 0),
    life = (d.health.life_time || '').split(/\s+/),
    ev = (k: string) => extValue(ext, k),
    raw = (k: string) => ev(k) || '尚未读取',
    decoded = (k: string) => decodeRegister(k, ev(k));
  const enhanced = (v: string) =>
    v &&
    ((/^\d+$/.test(v) && BigInt(v) > BigInt(d.size)) ||
      ['4294967274', '18446744073709551594'].includes(v))
      ? '未启用 / 内核未提供有效值'
      : v;
  const ios = d.mmc_link?.ios || {},
    modes = supportedModes(ev('CARD_TYPE') || ev('DEVICE_TYPE'), ev('STROBE_SUPPORT')),
    rate = currentBusRate(ios);
  const labels: Record<string, string> = {
    logical_block_size: '逻辑扇区大小（B）',
    physical_block_size: '物理扇区大小（B）',
    minimum_io_size: '最小 I/O 单元（B）',
    optimal_io_size: '最佳 I/O 单元（B）',
    rotational: '旋转介质（0=固态，1=机械）',
    scheduler: 'I/O 调度器',
    read_ahead_kb: '预读大小（KiB）',
    nr_requests: '请求队列深度',
    max_sectors_kb: '最大请求大小（KiB）',
    discard_granularity: 'TRIM / discard 粒度（B）',
    discard_max_bytes: '单次 discard 上限（B）',
    write_cache: '内核写缓存策略',
  };
  return (
    <div className="disk-full-details">
      <p className="disk-detail-note">
        标准寄存器优先显示解析结果，括号内保留原始值。CID、UUID
        及厂商固件编码保留原样；保留位或未知值明确标注，不推断含义。
      </p>
      <Group
        title="设备标识与连接"
        rows={[
          ['型号', d.model],
          ['设备节点', d.path],
          ['内核名称', d.kname],
          ['设备类型', ({ emmc: 'eMMC', sd: 'SD 卡', usb: 'USB 存储' } as any)[d.kind] || d.kind],
          ['传输接口', d.tran || (card.type ? 'MMC / ' + card.type : '设备未提供')],
          ['设备身份', d.identity],
          ['CID', d.cid],
          ['序列号', hexNumber(card.serial || d.serial)],
          ['制造日期', card.date],
          ['器件厂商（CID 识别）', manufacturer(card.manfid)],
          ['制造商 ID', hexNumber(card.manfid)],
          ['OEM ID', hexNumber(card.oemid)],
          ['硬件版本', hexNumber(card.hwrev)],
          ['固件版本（厂商编码）', card.fwrev],
          ['产品版本', productRevision(card.prv)],
          ['设备号（主:次）', block.dev],
          ['可移除', block.removable === '1' ? '是' : block.removable === '0' ? '否' : undefined],
          ['内核拓扑', d.topology],
          ['磁盘实例序号', block.diskseq],
        ]}
      />
      {d.kind === 'emmc' && (
        <p className="disk-detail-note">
          厂商名称由 CID 制造商 ID 识别，代表 eMMC 器件厂商。内部 NAND 裸晶型号、生产厂商和 MLC/TLC
          工艺不由标准寄存器提供，无法仅凭 H8G4a
          产品名确定；进一步识别需核对芯片封装丝印与对应厂商资料。
        </p>
      )}
      <Group
        title="容量、布局与访问状态"
        rows={[
          ['用户区精确容量', bytes(d.size)],
          ['512 B 扇区总数', d.size / 512],
          ['已分配分区容量', bytes(allocated)],
          ['分区外空间（含表及对齐预留）', bytes(Math.max(0, d.size - allocated))],
          ['分区数量', parts.length],
          [
            '分区表类型',
            d.table?.label === 'dos' ? 'MBR（DOS）' : d.table?.label?.toUpperCase() || '无分区表',
          ],
          ['分区表 ID', d.table?.id],
          ['分区表扇区单位（B）', d.table?.sectorsize || d.sector_size],
          ['首个可用 LBA', d.table?.firstlba],
          ['最后可用 LBA', d.table?.lastlba],
          ['系统磁盘保护', d.protected ? '已保护 · 禁止修改' : '非系统磁盘'],
          ['工具写入权限', d.writable ? '允许' : '禁止'],
          ['内核只读状态', d.ro ? '只读' : '可读写'],
          [
            '挂载位置',
            d.regions
              .flatMap((r: any) => r.mountpoints || [])
              .filter(Boolean)
              .join(' · ') || '未挂载',
          ],
        ]}
      />
      {d.kind === 'emmc' && (
        <>
          <Group
            title="eMMC 寿命与健康"
            rows={[
              ['寿命估计 A', `${lifetime(life[0])}（原值 ${life[0] || '未提供'}）`],
              ['寿命估计 B', `${lifetime(life[1])}（原值 ${life[1] || '未提供'}）`],
              ['寿命预警', `${preEol(d.health.pre_eol)}（原值 ${d.health.pre_eol || '未提供'}）`],
            ]}
          />
          <p className="disk-detail-note">
            寿命值是按 10% 档位报告的磨损估计，不是精确剩余百分比或剩余使用年限。A/B
            对应设备定义的两类存储区，具体介质类型由厂商定义。预警区间表示备用块已消耗比例，与 A/B
            磨损估计是不同指标；未提供和保留值不会当作健康正常。
          </p>
          <div className="eol-bands" aria-label="备用块消耗预警区间">
            {[
              { code: 1, label: '正常', range: '0–<80%', color: 'var(--health-good)' },
              { code: 2, label: '预警', range: '80–<90%', color: 'var(--health-warning)' },
              { code: 3, label: '紧急', range: '≥90%', color: 'var(--health-danger)' },
            ].map((b) => (
              <div
                key={b.code}
                style={{
                  borderColor: b.color,
                  opacity: Number(d.health.pre_eol) === b.code ? 1 : 0.7,
                }}
              >
                <b style={{ color: b.color }}>
                  {b.label} · {b.range}
                </b>
                <small>
                  备用块已消耗{Number(d.health.pre_eol) === b.code ? ' · 当前状态' : ''}
                </small>
              </div>
            ))}
          </div>
          <Group
            title="当前 MMC 链路（实时读取）"
            rows={[
              ['MMC 主机', d.mmc_link?.host],
              ['当前协议 / 时序', ios['timing spec']],
              [
                '实际时钟',
                ios['actual clock'] || ios.clock
                  ? `${parseInt(ios['actual clock'] || ios.clock) / 1e6} MHz（${ios['actual clock'] || ios.clock}）`
                  : undefined,
              ],
              ['总线宽度', ios['bus width']],
              ['信号电压', ios['signal voltage']],
              ['供电电压', ios.vdd],
              ['驱动类型', ios['driver type']],
              ['总线模式', ios['bus mode']],
              [
                '总线理论带宽',
                rate === null
                  ? '内核未提供足够信息'
                  : rate.toFixed(0) + ' MB/s（不等于实际读写速度）',
              ],
            ]}
          />
          <section className="disk-detail-group">
            <h4>支持的速率协议（EXT_CSD 能力）</h4>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>协议</th>
                    <th>时钟上限</th>
                    <th>传输方式</th>
                    <th>I/O 电压</th>
                    <th>8 位总线理论带宽</th>
                  </tr>
                </thead>
                <tbody>
                  {modes.map((m) => (
                    <tr key={m.mask}>
                      <td>
                        <b>{m.name}</b>
                      </td>
                      <td>{m.clock} MHz</td>
                      <td>{m.transfer}</td>
                      <td>{m.voltage}</td>
                      <td>{m.rate} MB/s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!modes.length && (
              <p className="disk-detail-note">尚未取得设备协议能力，请刷新 EXT_CSD。</p>
            )}
            <p className="disk-detail-note">
              能力寄存器 {raw('CARD_TYPE') === '尚未读取' ? raw('DEVICE_TYPE') : raw('CARD_TYPE')} ·
              SDR 每时钟传一次，DDR 每时钟传两次。带宽按 8
              位数据线计算，仅为接口理论上限，实际读写受
              NAND、控制器及工作负载影响。支持协议与当前协商协议分别展示。
            </p>
          </section>
          <Group
            title="eMMC 启动区、写保护与能力"
            rows={[
              [
                'eMMC / EXT_CSD 版本',
                ext.match(/Extended CSD rev[^\r\n]+/)?.[0] || (loading ? '正在读取…' : '尚未读取'),
              ],
              [
                '启动配置',
                bootConfig(ev('PARTITION_CONFIG')) + '（' + raw('PARTITION_CONFIG') + '）',
              ],
              ['启动总线条件', decoded('BOOT_BUS_CONDITIONS')],
              ['启动配置保护', decoded('BOOT_CONFIG_PROT')],
              ...d.regions
                .filter((r: any) => r.region.startsWith('boot'))
                .flatMap((r: any): [string, unknown][] => [
                  [r.region.toUpperCase() + ' 容量', bytes(r.size)],
                  [
                    r.region.toUpperCase() + ' 软件只读保护',
                    r.force_ro === '1'
                      ? '已开启（force_ro=1）'
                      : r.force_ro === '0'
                        ? '已关闭（force_ro=0）'
                        : '设备未提供',
                  ],
                  [r.region.toUpperCase() + ' 内核只读状态', r.ro ? '只读' : '可读写'],
                ]),
              ['BOOT 硬件写保护状态', decoded('BOOT_WP_STATUS')],
              ['BOOT 写保护配置', decoded('BOOT_WP')],
              ['用户区写保护配置', decoded('USER_WP')],
              ['RPMB 容量', bytes(d.rpmb.size)],
              ['RPMB 状态', d.rpmb.available ? '已发现认证设备节点' : '未发现设备节点'],
              ['RPMB 节点', d.rpmb.path],
              [
                '支持的速度模式（非当前工作速度）',
                ext.match(/Card Type[^\n]*\n((?:[ \t]+[^\n]*\n)+)/)?.[1]?.trim(),
              ],
              ['缓存容量', ext.match(/Cache Size[^\n]*is ([^\n]+)/)?.[1]],
              ['缓存开关', decoded('CACHE_CTRL')],
              ['擦除单元（B）', card.erase_size],
              ['建议擦除单元（B）', card.preferred_erase_size],
              ['可靠写入扇区数', hexNumber(card.rel_sectors)],
              ['可靠写入设置', decoded('WR_REL_SET')],
              ['硬件复位配置', decoded('RST_N_FUNCTION')],
              ['后台整理状态', decoded('BKOPS_STATUS')],
              ['后台整理启用', decoded('BKOPS_EN')],
              ['高速时序寄存器', decoded('HS_TIMING')],
              ['增强选通能力', decoded('STROBE_SUPPORT')],
              ['命令队列启用', binaryFlag(card.cmdq_en)],
              ['FFU 固件更新支持', binaryFlag(card.ffu_capable, '支持', '不支持')],
              ['增强区域起点（B）', enhanced(card.enhanced_area_offset)],
              ['增强区域容量（B）', enhanced(card.enhanced_area_size)],
            ]}
          />
          {error && (
            <p className="disk-detail-note">EXT_CSD 读取失败：{error}。其他信息仍来自当前设备。</p>
          )}
        </>
      )}
      <Group
        title="块设备与 I/O 参数"
        rows={Object.entries(labels).map(([k, label]) => [label, queue[k]])}
      />
      <section className="disk-detail-group">
        <h4>分区及存储区域详细信息</h4>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>区域 / 节点</th>
                <th>精确容量 / 扇区</th>
                <th>文件系统 / 标识</th>
                <th>访问状态</th>
              </tr>
            </thead>
            <tbody>
              {d.regions.map((r: any) => (
                <tr key={r.path}>
                  <td>
                    <b>
                      {r.region === 'user'
                        ? '用户区'
                        : r.region === 'partition'
                          ? '分区 ' + r.name
                          : r.region.toUpperCase()}
                    </b>
                    <small>{r.path}</small>
                  </td>
                  <td>
                    {bytes(r.size)}
                    <small>{r.size / 512} 个 512 B 扇区</small>
                    <small>
                      {r.region === 'partition'
                        ? `起点 ${r.start} · 末扇区 ${Number(r.start) + r.size / 512 - 1}`
                        : '独立地址空间 · 从偏移 0 开始'}
                    </small>
                  </td>
                  <td>
                    {r.fstype || '无已识别文件系统'}
                    <small>
                      卷标：{r.label || '—'} · 分区名：{r.partlabel || '—'}
                    </small>
                    <small>UUID：{r.uuid || '—'}</small>
                    <small>PARTUUID：{r.partuuid || '—'}</small>
                    <small>类型：{partitionType(r.parttype)}</small>
                  </td>
                  <td>
                    {r.ro ? '只读' : '可读写'}
                    <small>{(r.mountpoints || []).filter(Boolean).join(' · ') || '未挂载'}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Group
        title="卡片寄存器与解析"
        rows={[
          ['CID 原值', card.cid],
          ['CSD 原值', card.csd],
          ['OCR 供电电压掩码', d.kind === 'emmc' ? ocrInfo(card.ocr) : card.ocr],
          ['RCA 相对卡地址', hexNumber(card.rca)],
          ['DSR 驱动阶段寄存器', hexNumber(card.dsr)],
          ...(d.kind === 'emmc' ? mmcCsd(card.csd) : []),
        ]}
      />
      <details className="ext-details">
        <summary>全部发现数据（JSON 原值）</summary>
        <pre>{JSON.stringify(d, null, 2)}</pre>
      </details>
      {ext && (
        <details className="ext-details">
          <summary>完整 EXT_CSD 输出（包含全部配置与能力）</summary>
          <pre>{ext}</pre>
        </details>
      )}
    </div>
  );
}
