# Review & Amend – 交接说明(给开发 agents)

配套文件:`review-amend-prototype.html`(视觉与交互的唯一参考)。

## 1. 目标
把现有「三层抽屉 + 4 个 Tab 向导 + 4 个决策按钮」改成 **单页左右分栏表单**,风格对齐 Orbyte 的 Edit User / Edit Project:
表单字段上下排列、必填带 `*`、底部固定操作栏 Cancel + Save。

## 2. 布局
- 页面或大型 Modal,最大宽度 1280px。
- 顶部:ReviewHeader(返回、标题、状态 chip、版本 chip、More actions 菜单)。
- StatusStrip:Processing / Information / Identity / Review 四项。
- IssueBanner:有缺失或冲突字段时显示,全部解决后隐藏。
- 主体 `5fr : 7fr` 两栏:
  - 左:SourceMessagePanel,只读,sticky,可内部滚动。
  - 右:AmendForm(可编辑)。
- 底部:StickyActionBar(固定)。
- ≤900px 变单栏,左侧原文放上面,不 sticky。

## 3. 组件映射(原型里的 `data-component`)
| 名称 | 说明 |
|---|---|
| ReviewHeader | 标题 + chips + 右侧 MoreActionsMenu |
| MoreActionsMenu | Request more info / Mark unresolved / Reprocess extraction |
| StatusStrip | 4 列只读状态 |
| IssueBanner | 红色提示条 |
| SourceMessagePanel | 原文,字段对应文字用 `<mark data-key>` 高亮 |
| AmendForm | 右侧所有可编辑区域 |
| FieldRow | label + 状态 chip + 证据按钮 + 输入 + helper 文案 |
| ItemsTable | 商品行:Product / Qty / Unit(下拉) / 证据按钮 |
| AISuggestion | AI 建议问题 + "Use as clarification note" |
| AuditNoteCard | Reviewer note(必填) |
| TechnicalDetails | `<details>` 默认收起,放 GLiNER / Qwen / GPU / Pipeline 信息 |
| StickyActionBar | 左侧脏状态文字,右侧按钮 |

## 4. 行为规则
1. **字段联动**:字段 focus 或 click 时,左侧对应 `mark`(同一个 `data-key`)高亮并滚动到可视区。
2. **证据**:每个字段旁 🔍 按钮,点击展开该字段的 evidence quote 与 offset、method;默认折叠,避免截断。
3. **状态 chip**:`Missing`(红)/ `Unresolved`(黄)/ `Confirmed`(绿),随输入实时更新。
4. **校验**:
   - Save changes:有修改 **且** Reviewer note 非空即可用。
   - Save & Accept:额外要求所有必填字段已解决(单位、时区)。
5. **Dirty 状态**:底部左侧显示 "No changes yet / Unsaved changes / … reviewer note is required"。
6. **AI 建议**:点 "Use as clarification note" 把建议文字写入 Reviewer note(仍需员工审核后才会发给客户,保留 "Requires staff approval" 标签)。
7. **More actions**:
   - Request more info:用 AI 建议(或 Reviewer note)作为内容,进入员工审批,Review 状态变 "Waiting for customer"。
   - Mark unresolved:使用橙色(非危险色),Review 状态变 "Unresolved"。
   - Reprocess extraction:保持原有逻辑。
8. **审计**:所有保存动作必须写入 context timeline,带 Reviewer note 作为 audited reason。
9. **技术信息**默认折叠,只给管理员/工程师展开查看。

## 5. 视觉规范
- 颜色、间距、圆角全部来自 `:root` 的 CSS 变量,**请映射到项目现有 theme / design tokens,不要硬编码**。
- 按钮:主按钮蓝底白字;次按钮白底灰边。底部栏只用 Cancel / Save changes / Save & Accept。
- 红色只用于"缺失/错误",不用于 Mark unresolved。
- Evidence quote 不再放表格列里,避免被截断。

## 6. 与 Orbyte 的兼容点
- 必填 `*`、输入框圆角和边框风格、ACTIVE/INACTIVE 式小标签、白色卡片 + 浅灰蓝页面背景。
- 底部固定操作栏取代原来的多按钮区域。
- 若项目已有 Orbyte 的 Form / Card / Chip / Button 组件,**优先复用,不要重写**。

## 7. 验收清单
- [ ] 不再有 4 个 Tab 和 Back/Next 向导。
- [ ] 左侧原文与右侧字段同屏可见,点字段能定位原文。
- [ ] 底部只有 Cancel / Save changes / Save & Accept。
- [ ] Request more info / Mark unresolved 在 More actions 菜单里。
- [ ] 技术信息默认折叠。
- [ ] Evidence 不被截断,点开可看。
- [ ] 1280px 与 ≤900px 两种宽度显示正常。
- [ ] 与原型对比,间距、颜色、字号误差肉眼可接受。
