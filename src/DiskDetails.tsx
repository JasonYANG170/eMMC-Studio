import { t, locale } from './i18n.js';
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
            <dd>{v === undefined || v === null || v === '' ? t('设备未提供') : String(v)}</dd>
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
    raw = (k: string) => ev(k) || t('尚未读取'),
    decoded = (k: string) => decodeRegister(k, ev(k));
  const enhanced = (v: string) =>
    v &&
    ((/^\d+$/.test(v) && BigInt(v) > BigInt(d.size)) ||
      ['4294967274', '18446744073709551594'].includes(v))
      ? t('未启用 / 内核未提供有效值')
      : v;
  const ios = d.mmc_link?.ios || {},
    modes = supportedModes(ev('CARD_TYPE') || ev('DEVICE_TYPE'), ev('STROBE_SUPPORT')),
    rate = currentBusRate(ios);
  const labels: Record<string, string> = {
    logical_block_size: t('逻辑扇区大小（B）'),
    physical_block_size: t('物理扇区大小（B）'),
    minimum_io_size: t('最小 I/O 单元（B）'),
    optimal_io_size: t('最佳 I/O 单元（B）'),
    rotational: t('旋转介质（0=固态，1=机械）'),
    scheduler: t('I/O 调度器'),
    read_ahead_kb: t('预读大小（KiB）'),
    nr_requests: t('请求队列深度'),
    max_sectors_kb: t('最大请求大小（KiB）'),
    discard_granularity: t('TRIM / discard 粒度（B）'),
    discard_max_bytes: t('单次 discard 上限（B）'),
    write_cache: t('内核写缓存策略'),
  };
  return (
    <div className="disk-full-details">
      <p className="disk-detail-note">
        {t(
          '标准寄存器优先显示解析结果，括号内保留原始值。CID、UUID 及厂商固件编码保留原样；保留位或未知值明确标注，不推断含义。',
        )}
      </p>
      <Group
        title={t('设备标识与连接')}
        rows={[
          [t('型号'), d.model],
          [t('设备节点'), d.path],
          [t('内核名称'), d.kname],
          [
            t('设备类型'),
            ({ emmc: 'eMMC', sd: t('SD 卡'), usb: t('USB 存储') } as any)[d.kind] || d.kind,
          ],
          [t('传输接口'), d.tran || (card.type ? 'MMC / ' + card.type : t('设备未提供'))],
          [t('设备身份'), d.identity],
          ['CID', d.cid],
          [t('序列号'), hexNumber(card.serial || d.serial)],
          [t('制造日期'), card.date],
          [t('器件厂商（CID 识别）'), manufacturer(card.manfid)],
          [t('制造商 ID'), hexNumber(card.manfid)],
          ['OEM ID', hexNumber(card.oemid)],
          [t('硬件版本'), hexNumber(card.hwrev)],
          [t('固件版本（厂商编码）'), card.fwrev],
          [t('产品版本'), productRevision(card.prv)],
          [t('设备号（主:次）'), block.dev],
          [
            t('可移除'),
            block.removable === '1' ? t('是') : block.removable === '0' ? t('否') : undefined,
          ],
          [t('内核拓扑'), d.topology],
          [t('磁盘实例序号'), block.diskseq],
        ]}
      />
      {d.kind === 'emmc' && (
        <p className="disk-detail-note">
          {t(
            '厂商名称由 CID 制造商 ID 识别，代表 eMMC 器件厂商。内部 NAND 裸晶型号、生产厂商和 MLC/TLC 工艺不由标准寄存器提供，无法仅凭 H8G4a 产品名确定；进一步识别需核对芯片封装丝印与对应厂商资料。',
          )}
        </p>
      )}
      <Group
        title={t('容量、布局与访问状态')}
        rows={[
          [t('用户区精确容量'), bytes(d.size)],
          [t('512 B 扇区总数'), d.size / 512],
          [t('已分配分区容量'), bytes(allocated)],
          [t('分区外空间（含表及对齐预留）'), bytes(Math.max(0, d.size - allocated))],
          [t('分区数量'), parts.length],
          [
            t('分区表类型'),
            d.table?.label === 'dos'
              ? 'MBR（DOS）'
              : d.table?.label?.toUpperCase() || t('无分区表'),
          ],
          [t('分区表 ID'), d.table?.id],
          [t('分区表扇区单位（B）'), d.table?.sectorsize || d.sector_size],
          [t('首个可用 LBA'), d.table?.firstlba],
          [t('最后可用 LBA'), d.table?.lastlba],
          [t('系统磁盘保护'), d.protected ? t('已保护 · 禁止修改') : t('非系统磁盘')],
          [t('工具写入权限'), d.writable ? t('允许') : t('禁止')],
          [t('内核只读状态'), d.ro ? t('只读') : t('可读写')],
          [
            t('挂载位置'),
            d.regions
              .flatMap((r: any) => r.mountpoints || [])
              .filter(Boolean)
              .join(' · ') || t('未挂载'),
          ],
        ]}
      />
      {d.kind === 'emmc' && (
        <>
          <Group
            title={t('eMMC 寿命与健康')}
            rows={[
              [t('寿命估计 A'), t('{0}（原值 {1}）', [lifetime(life[0]), life[0] || t('未提供')])],
              [t('寿命估计 B'), t('{0}（原值 {1}）', [lifetime(life[1]), life[1] || t('未提供')])],
              [
                t('寿命预警'),
                t('{0}（原值 {1}）', [preEol(d.health.pre_eol), d.health.pre_eol || t('未提供')]),
              ],
            ]}
          />
          <p className="disk-detail-note">
            {t(
              '寿命值是按 10% 档位报告的磨损估计，不是精确剩余百分比或剩余使用年限。A/B 对应设备定义的两类存储区，具体介质类型由厂商定义。预警区间表示备用块已消耗比例，与 A/B 磨损估计是不同指标；未提供和保留值不会当作健康正常。',
            )}
          </p>
          <div className="eol-bands" aria-label={t('备用块消耗预警区间')}>
            {[
              { code: 1, label: t('正常'), range: '0–<80%', color: 'var(--health-good)' },
              { code: 2, label: t('预警'), range: '80–<90%', color: 'var(--health-warning)' },
              { code: 3, label: t('紧急'), range: '≥90%', color: 'var(--health-danger)' },
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
                  {t('备用块已消耗')}
                  {Number(d.health.pre_eol) === b.code ? t(' · 当前状态') : ''}
                </small>
              </div>
            ))}
          </div>
          <Group
            title={t('当前 MMC 链路（实时读取）')}
            rows={[
              [t('MMC 主机'), d.mmc_link?.host],
              [t('当前协议 / 时序'), ios['timing spec']],
              [
                t('实际时钟'),
                ios['actual clock'] || ios.clock
                  ? `${parseInt(ios['actual clock'] || ios.clock) / 1e6} MHz（${ios['actual clock'] || ios.clock}）`
                  : undefined,
              ],
              [t('总线宽度'), ios['bus width']],
              [t('信号电压'), ios['signal voltage']],
              [t('供电电压'), ios.vdd],
              [t('驱动类型'), ios['driver type']],
              [t('总线模式'), ios['bus mode']],
              [
                t('总线理论带宽'),
                rate === null
                  ? t('内核未提供足够信息')
                  : rate.toFixed(0) + t(' MB/s（不等于实际读写速度）'),
              ],
            ]}
          />
          <section className="disk-detail-group">
            <h4>{t('支持的速率协议（EXT_CSD 能力）')}</h4>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t('协议')}</th>
                    <th>{t('时钟上限')}</th>
                    <th>{t('传输方式')}</th>
                    <th>{t('I/O 电压')}</th>
                    <th>{t('8 位总线理论带宽')}</th>
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
              <p className="disk-detail-note">{t('尚未取得设备协议能力，请刷新 EXT_CSD。')}</p>
            )}
            <p className="disk-detail-note">
              {t('能力寄存器')}
              {raw('CARD_TYPE') === t('尚未读取') ? raw('DEVICE_TYPE') : raw('CARD_TYPE')}
              {t(
                '· SDR 每时钟传一次，DDR 每时钟传两次。带宽按 8 位数据线计算，仅为接口理论上限，实际读写受 NAND、控制器及工作负载影响。支持协议与当前协商协议分别展示。',
              )}
            </p>
          </section>
          <Group
            title={t('eMMC 启动区、写保护与能力')}
            rows={[
              [
                t('eMMC / EXT_CSD 版本'),
                ext.match(/Extended CSD rev[^\r\n]+/)?.[0] ||
                  (loading ? t('正在读取…') : t('尚未读取')),
              ],
              [
                t('启动配置'),
                bootConfig(ev('PARTITION_CONFIG')) + '（' + raw('PARTITION_CONFIG') + '）',
              ],
              [t('启动总线条件'), decoded('BOOT_BUS_CONDITIONS')],
              [t('启动配置保护'), decoded('BOOT_CONFIG_PROT')],
              ...d.regions
                .filter((r: any) => r.region.startsWith('boot'))
                .flatMap((r: any): [string, unknown][] => [
                  [r.region.toUpperCase() + t(' 容量'), bytes(r.size)],
                  [
                    r.region.toUpperCase() + t(' 软件只读保护'),
                    r.force_ro === '1'
                      ? t('已开启（force_ro=1）')
                      : r.force_ro === '0'
                        ? t('已关闭（force_ro=0）')
                        : t('设备未提供'),
                  ],
                  [r.region.toUpperCase() + t(' 内核只读状态'), r.ro ? t('只读') : t('可读写')],
                ]),
              [t('BOOT 硬件写保护状态'), decoded('BOOT_WP_STATUS')],
              [t('BOOT 写保护配置'), decoded('BOOT_WP')],
              [t('用户区写保护配置'), decoded('USER_WP')],
              [t('RPMB 容量'), bytes(d.rpmb.size)],
              [t('RPMB 状态'), d.rpmb.available ? t('已发现认证设备节点') : t('未发现设备节点')],
              [t('RPMB 节点'), d.rpmb.path],
              [
                t('支持的速度模式（非当前工作速度）'),
                ext.match(/Card Type[^\n]*\n((?:[ \t]+[^\n]*\n)+)/)?.[1]?.trim(),
              ],
              [t('缓存容量'), ext.match(/Cache Size[^\n]*is ([^\n]+)/)?.[1]],
              [t('缓存开关'), decoded('CACHE_CTRL')],
              [t('擦除单元（B）'), card.erase_size],
              [t('建议擦除单元（B）'), card.preferred_erase_size],
              [t('可靠写入扇区数'), hexNumber(card.rel_sectors)],
              [t('可靠写入设置'), decoded('WR_REL_SET')],
              [t('硬件复位配置'), decoded('RST_N_FUNCTION')],
              [t('后台整理状态'), decoded('BKOPS_STATUS')],
              [t('后台整理启用'), decoded('BKOPS_EN')],
              [t('高速时序寄存器'), decoded('HS_TIMING')],
              [t('增强选通能力'), decoded('STROBE_SUPPORT')],
              [t('命令队列启用'), binaryFlag(card.cmdq_en)],
              [t('FFU 固件更新支持'), binaryFlag(card.ffu_capable, t('支持'), t('不支持'))],
              [t('增强区域起点（B）'), enhanced(card.enhanced_area_offset)],
              [t('增强区域容量（B）'), enhanced(card.enhanced_area_size)],
            ]}
          />
          {error && (
            <p className="disk-detail-note">
              {t('EXT_CSD 读取失败：')}
              {error}
              {t('。其他信息仍来自当前设备。')}
            </p>
          )}
        </>
      )}
      <Group
        title={t('块设备与 I/O 参数')}
        rows={Object.entries(labels).map(([k, label]) => [label, queue[k]])}
      />
      <section className="disk-detail-group">
        <h4>{t('分区及存储区域详细信息')}</h4>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t('区域 / 节点')}</th>
                <th>{t('精确容量 / 扇区')}</th>
                <th>{t('文件系统 / 标识')}</th>
                <th>{t('访问状态')}</th>
              </tr>
            </thead>
            <tbody>
              {d.regions.map((r: any) => (
                <tr key={r.path}>
                  <td>
                    <b>
                      {r.region === 'user'
                        ? t('用户区')
                        : r.region === 'partition'
                          ? t('分区 ') + r.name
                          : r.region.toUpperCase()}
                    </b>
                    <small>{r.path}</small>
                  </td>
                  <td>
                    {bytes(r.size)}
                    <small>
                      {r.size / 512}
                      {t('个 512 B 扇区')}
                    </small>
                    <small>
                      {r.region === 'partition'
                        ? t('起点 {0} · 末扇区 {1}', [r.start, Number(r.start) + r.size / 512 - 1])
                        : t('独立地址空间 · 从偏移 0 开始')}
                    </small>
                  </td>
                  <td>
                    {r.fstype || t('无已识别文件系统')}
                    <small>
                      {t('卷标：')}
                      {r.label || '—'}
                      {t('· 分区名：')}
                      {r.partlabel || '—'}
                    </small>
                    <small>UUID：{r.uuid || '—'}</small>
                    <small>PARTUUID：{r.partuuid || '—'}</small>
                    <small>
                      {t('类型：')}
                      {partitionType(r.parttype)}
                    </small>
                  </td>
                  <td>
                    {r.ro ? t('只读') : t('可读写')}
                    <small>
                      {(r.mountpoints || []).filter(Boolean).join(' · ') || t('未挂载')}
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Group
        title={t('卡片寄存器与解析')}
        rows={[
          [t('CID 原值'), card.cid],
          [t('CSD 原值'), card.csd],
          [t('OCR 供电电压掩码'), d.kind === 'emmc' ? ocrInfo(card.ocr) : card.ocr],
          [t('RCA 相对卡地址'), hexNumber(card.rca)],
          [t('DSR 驱动阶段寄存器'), hexNumber(card.dsr)],
          ...(d.kind === 'emmc' ? mmcCsd(card.csd) : []),
        ]}
      />
      <details className="ext-details">
        <summary>{t('全部发现数据（JSON 原值）')}</summary>
        <pre>{JSON.stringify(d, null, 2)}</pre>
      </details>
      {ext && (
        <details className="ext-details">
          <summary>{t('完整 EXT_CSD 输出（包含全部配置与能力）')}</summary>
          <pre>{ext}</pre>
        </details>
      )}
    </div>
  );
}
