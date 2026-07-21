interface AdminBrandProps {
  compact?: boolean
}

const AdminBrand = ({ compact = false }: AdminBrandProps) => (
  <span className={`admin-brand ${compact ? 'admin-brand--compact' : ''}`}>
    <span className="admin-brand__mark" aria-hidden="true">
      <svg viewBox="0 0 54 44">
        <g transform="translate(0 44) scale(1 -1)">
          <path d="M5 34C12 7 23 9 22 23C21 36 33 38 35 22C37 8 45 8 50 13" />
          <circle className="admin-mark-node admin-mark-node--one" cx="5" cy="34" r="3.1" />
          <circle className="admin-mark-node admin-mark-node--two" cx="22" cy="23" r="3.1" />
          <circle className="admin-mark-node admin-mark-node--three" cx="35" cy="22" r="3.1" />
          <circle className="admin-mark-node admin-mark-node--four" cx="50" cy="13" r="3.1" />
        </g>
      </svg>
    </span>
    <span className="admin-brand__name">
      <b>408</b>
      <strong>管理工作台</strong>
    </span>
  </span>
)

export default AdminBrand
