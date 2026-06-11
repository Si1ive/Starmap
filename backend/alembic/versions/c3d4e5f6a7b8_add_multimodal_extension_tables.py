"""add_multimodal_extension_tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-11 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. canonical_chapters - 标准章节表
    op.create_table('canonical_chapters',
        sa.Column('id', sa.String(32), nullable=False, comment='章节ID'),
        sa.Column('subject_id', sa.String(32), nullable=False, comment='所属学科ID'),
        sa.Column('parent_id', sa.String(32), nullable=True, comment='父章节ID'),
        sa.Column('level', sa.Integer(), nullable=False, default=1, comment='层级'),
        sa.Column('name', sa.String(200), nullable=False, comment='标准章节名称'),
        sa.Column('code', sa.String(50), nullable=True, comment='章节编码'),
        sa.Column('aliases', sa.JSON(), nullable=True, comment='别名列表'),
        sa.Column('description', sa.Text(), nullable=True, comment='章节描述'),
        sa.Column('sort_order', sa.Integer(), nullable=False, default=0, comment='排序序号'),
        sa.Column('status', sa.Enum('active', 'inactive'), nullable=False, default='active', comment='状态'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['canonical_chapters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='标准章节表'
    )
    op.create_index('idx_canonical_chapters_subject', 'canonical_chapters', ['subject_id'])
    op.create_index('idx_canonical_chapters_parent', 'canonical_chapters', ['parent_id'])
    op.create_index('idx_canonical_chapters_level', 'canonical_chapters', ['level'])

    # 2. document_sections - 文档原生标题树
    op.create_table('document_sections',
        sa.Column('id', sa.String(32), nullable=False, comment='section ID'),
        sa.Column('document_id', sa.String(32), nullable=False, comment='文档ID'),
        sa.Column('parent_id', sa.String(32), nullable=True, comment='父section ID'),
        sa.Column('level', sa.Integer(), nullable=False, comment='层级深度'),
        sa.Column('title', sa.String(500), nullable=False, comment='原生标题文本'),
        sa.Column('section_path', sa.String(1000), nullable=False, comment='完整路径'),
        sa.Column('page_start', sa.Integer(), nullable=True, comment='起始页码'),
        sa.Column('page_end', sa.Integer(), nullable=True, comment='结束页码'),
        sa.Column('block_start_id', sa.String(32), nullable=True, comment='起始block ID'),
        sa.Column('block_end_id', sa.String(32), nullable=True, comment='结束block ID'),
        sa.Column('confidence', sa.DECIMAL(5, 4), nullable=True, comment='识别置信度'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['document_sections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='文档原生标题树'
    )
    op.create_index('idx_document_sections_document', 'document_sections', ['document_id'])
    op.create_index('idx_document_sections_parent', 'document_sections', ['parent_id'])
    op.create_index('idx_document_sections_level', 'document_sections', ['level'])

    # 3. document_section_mappings - 文档section到标准章节的映射
    op.create_table('document_section_mappings',
        sa.Column('id', sa.String(32), nullable=False, comment='映射ID'),
        sa.Column('document_section_id', sa.String(32), nullable=False, comment='文档section ID'),
        sa.Column('canonical_chapter_id', sa.String(32), nullable=False, comment='标准章节ID'),
        sa.Column('mapping_type', sa.Enum('exact', 'partial', 'related'), nullable=False, default='exact', comment='映射类型'),
        sa.Column('confidence', sa.DECIMAL(5, 4), nullable=False, comment='映射置信度'),
        sa.Column('review_status', sa.Enum('pending', 'approved', 'rejected'), nullable=False, default='pending', comment='审核状态'),
        sa.Column('review_notes', sa.Text(), nullable=True, comment='审核备注'),
        sa.Column('reviewed_by', sa.String(32), nullable=True, comment='审核人'),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True, comment='审核时间'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_section_id'], ['document_sections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['canonical_chapter_id'], ['canonical_chapters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='文档section到标准章节的映射'
    )
    op.create_index('idx_dsm_section', 'document_section_mappings', ['document_section_id'])
    op.create_index('idx_dsm_chapter', 'document_section_mappings', ['canonical_chapter_id'])
    op.create_index('idx_dsm_review_status', 'document_section_mappings', ['review_status'])
    op.create_index('idx_dsm_confidence', 'document_section_mappings', ['confidence'])

    # 4. 扩展 knowledge_points 表
    op.add_column('knowledge_points', sa.Column('primary_chapter_id', sa.String(32), nullable=True, comment='主标准章节ID'))
    op.add_column('knowledge_points', sa.Column('source_document_id', sa.String(32), nullable=True, comment='来源文档ID'))
    op.add_column('knowledge_points', sa.Column('canonical_title', sa.String(200), nullable=True, comment='标准化标题'))
    op.add_column('knowledge_points', sa.Column('topic_terms', sa.JSON(), nullable=True, comment='主题术语列表'))
    op.add_column('knowledge_points', sa.Column('aliases', sa.JSON(), nullable=True, comment='别名列表'))
    op.add_column('knowledge_points', sa.Column('review_status', sa.Enum('pending', 'approved', 'rejected'), nullable=False, default='pending', comment='审核状态'))
    op.add_column('knowledge_points', sa.Column('review_notes', sa.Text(), nullable=True, comment='审核备注'))
    op.create_foreign_key('fk_kp_primary_chapter', 'knowledge_points', 'canonical_chapters', ['primary_chapter_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_kp_source_document', 'knowledge_points', 'documents', ['source_document_id'], ['id'], ondelete='SET NULL')
    op.create_index('idx_kp_primary_chapter', 'knowledge_points', ['primary_chapter_id'])
    op.create_index('idx_kp_review_status', 'knowledge_points', ['review_status'])

    # 5. 扩展 questions 表
    op.add_column('questions', sa.Column('primary_chapter_id', sa.String(32), nullable=True, comment='主标准章节ID'))
    op.add_column('questions', sa.Column('source_document_id', sa.String(32), nullable=True, comment='来源文档ID'))
    op.add_column('questions', sa.Column('exam_scope', sa.String(50), nullable=True, comment='考试范围'))
    op.add_column('questions', sa.Column('paper_name', sa.String(255), nullable=True, comment='试卷名称'))
    op.add_column('questions', sa.Column('question_no', sa.String(20), nullable=True, comment='题号'))
    op.add_column('questions', sa.Column('topic_terms', sa.JSON(), nullable=True, comment='主题术语列表'))
    op.add_column('questions', sa.Column('review_status', sa.Enum('pending', 'approved', 'rejected'), nullable=False, default='pending', comment='审核状态'))
    op.add_column('questions', sa.Column('review_notes', sa.Text(), nullable=True, comment='审核备注'))
    op.create_foreign_key('fk_q_primary_chapter', 'questions', 'canonical_chapters', ['primary_chapter_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_q_source_document', 'questions', 'documents', ['source_document_id'], ['id'], ondelete='SET NULL')
    op.create_index('idx_q_primary_chapter', 'questions', ['primary_chapter_id'])
    op.create_index('idx_q_exam_scope', 'questions', ['exam_scope'])
    op.create_index('idx_q_review_status', 'questions', ['review_status'])

    # 6. knowledge_point_chapter_links - 知识点与章节关联表
    op.create_table('knowledge_point_chapter_links',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('knowledge_point_id', sa.String(32), nullable=False, comment='知识点ID'),
        sa.Column('canonical_chapter_id', sa.String(32), nullable=False, comment='标准章节ID'),
        sa.Column('is_primary', sa.Boolean(), nullable=False, default=False, comment='是否主章节'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['canonical_chapter_id'], ['canonical_chapters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('knowledge_point_id', 'canonical_chapter_id', name='uk_kp_chapter_link'),
        comment='知识点与章节关联表'
    )
    op.create_index('idx_kpcl_knowledge_point', 'knowledge_point_chapter_links', ['knowledge_point_id'])
    op.create_index('idx_kpcl_chapter', 'knowledge_point_chapter_links', ['canonical_chapter_id'])

    # 7. question_chapter_links - 题目与章节关联表
    op.create_table('question_chapter_links',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('question_id', sa.String(32), nullable=False, comment='题目ID'),
        sa.Column('canonical_chapter_id', sa.String(32), nullable=False, comment='标准章节ID'),
        sa.Column('is_primary', sa.Boolean(), nullable=False, default=False, comment='是否主章节'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['canonical_chapter_id'], ['canonical_chapters.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'canonical_chapter_id', name='uk_q_chapter_link'),
        comment='题目与章节关联表'
    )
    op.create_index('idx_qcl_question', 'question_chapter_links', ['question_id'])
    op.create_index('idx_qcl_chapter', 'question_chapter_links', ['canonical_chapter_id'])

    # 8. entity_source_links - 实体来源引用表
    op.create_table('entity_source_links',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('entity_type', sa.Enum('knowledge_point', 'question'), nullable=False, comment='实体类型'),
        sa.Column('entity_id', sa.String(32), nullable=False, comment='实体ID'),
        sa.Column('document_id', sa.String(32), nullable=False, comment='来源文档ID'),
        sa.Column('page_start', sa.Integer(), nullable=True, comment='起始页码'),
        sa.Column('page_end', sa.Integer(), nullable=True, comment='结束页码'),
        sa.Column('block_ids', sa.JSON(), nullable=True, comment='来源block ID列表'),
        sa.Column('excerpt_text', sa.Text(), nullable=True, comment='来源摘录文本'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='实体来源引用表'
    )
    op.create_index('idx_esl_entity', 'entity_source_links', ['entity_type', 'entity_id'])
    op.create_index('idx_esl_document', 'entity_source_links', ['document_id'])

    # 9. knowledge_relations - 知识点关系表
    op.create_table('knowledge_relations',
        sa.Column('id', sa.String(32), nullable=False, comment='关系ID'),
        sa.Column('source_knowledge_id', sa.String(32), nullable=False, comment='源知识点ID'),
        sa.Column('target_knowledge_id', sa.String(32), nullable=False, comment='目标知识点ID'),
        sa.Column('relation_type', sa.Enum('prerequisite', 'contrast_with', 'common_confusion', 'contains', 'part_of', 'used_in', 'similar_to'), nullable=False, comment='关系类型'),
        sa.Column('directionality', sa.Enum('directed', 'undirected'), nullable=False, default='directed', comment='方向性'),
        sa.Column('evidence_text', sa.Text(), nullable=True, comment='证据文本'),
        sa.Column('evidence_page', sa.Integer(), nullable=True, comment='证据页码'),
        sa.Column('confidence', sa.DECIMAL(5, 4), nullable=True, comment='置信度'),
        sa.Column('source_type', sa.Enum('rule', 'llm', 'manual', 'term_similarity'), nullable=False, default='llm', comment='来源类型'),
        sa.Column('review_status', sa.Enum('pending', 'approved', 'rejected'), nullable=False, default='pending', comment='审核状态'),
        sa.Column('review_notes', sa.Text(), nullable=True, comment='审核备注'),
        sa.Column('reviewed_by', sa.String(32), nullable=True, comment='审核人'),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True, comment='审核时间'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['source_knowledge_id'], ['knowledge_points.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_knowledge_id'], ['knowledge_points.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='知识点关系表'
    )
    op.create_index('idx_kr_source', 'knowledge_relations', ['source_knowledge_id'])
    op.create_index('idx_kr_target', 'knowledge_relations', ['target_knowledge_id'])
    op.create_index('idx_kr_type', 'knowledge_relations', ['relation_type'])
    op.create_index('idx_kr_review_status', 'knowledge_relations', ['review_status'])

    # 10. retrieval_segments - 检索单元表
    op.create_table('retrieval_segments',
        sa.Column('id', sa.String(32), nullable=False, comment='segment ID'),
        sa.Column('entity_type', sa.Enum('knowledge_point', 'question'), nullable=False, comment='实体类型'),
        sa.Column('entity_id', sa.String(32), nullable=False, comment='实体ID'),
        sa.Column('document_id', sa.String(32), nullable=True, comment='来源文档ID'),
        sa.Column('segment_type', sa.Enum('content', 'title', 'explanation', 'option'), nullable=False, default='content', comment='段落类型'),
        sa.Column('content_text', sa.Text(), nullable=False, comment='段落文本'),
        sa.Column('content_md', sa.Text(), nullable=True, comment='Markdown格式'),
        sa.Column('sparse_text', sa.Text(), nullable=True, comment='稀疏检索文本'),
        sa.Column('context_text', sa.Text(), nullable=True, comment='上下文增强文本'),
        sa.Column('page_no', sa.Integer(), nullable=True, comment='页码'),
        sa.Column('subject_id', sa.String(32), nullable=True, comment='学科ID'),
        sa.Column('chapter_ids', sa.JSON(), nullable=True, comment='章节ID列表'),
        sa.Column('topic_terms', sa.JSON(), nullable=True, comment='主题术语'),
        sa.Column('metadata_json', sa.JSON(), nullable=True, comment='扩展元数据'),
        sa.Column('qdrant_point_id', sa.String(100), nullable=True, comment='Qdrant point ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        comment='检索单元表'
    )
    op.create_index('idx_rs_entity', 'retrieval_segments', ['entity_type', 'entity_id'])
    op.create_index('idx_rs_document', 'retrieval_segments', ['document_id'])
    op.create_index('idx_rs_subject', 'retrieval_segments', ['subject_id'])
    op.create_index('idx_rs_segment_type', 'retrieval_segments', ['segment_type'])


def downgrade() -> None:
    # 按照相反的顺序删除
    op.drop_table('retrieval_segments')
    op.drop_table('knowledge_relations')
    op.drop_table('entity_source_links')
    op.drop_table('question_chapter_links')
    op.drop_table('knowledge_point_chapter_links')

    # 删除 questions 表的新列
    op.drop_index('idx_q_review_status', 'questions')
    op.drop_index('idx_q_exam_scope', 'questions')
    op.drop_index('idx_q_primary_chapter', 'questions')
    op.drop_constraint('fk_q_source_document', 'questions', type_='foreignkey')
    op.drop_constraint('fk_q_primary_chapter', 'questions', type_='foreignkey')
    op.drop_column('questions', 'review_notes')
    op.drop_column('questions', 'review_status')
    op.drop_column('questions', 'topic_terms')
    op.drop_column('questions', 'question_no')
    op.drop_column('questions', 'paper_name')
    op.drop_column('questions', 'exam_scope')
    op.drop_column('questions', 'source_document_id')
    op.drop_column('questions', 'primary_chapter_id')

    # 删除 knowledge_points 表的新列
    op.drop_index('idx_kp_review_status', 'knowledge_points')
    op.drop_index('idx_kp_primary_chapter', 'knowledge_points')
    op.drop_constraint('fk_kp_source_document', 'knowledge_points', type_='foreignkey')
    op.drop_constraint('fk_kp_primary_chapter', 'knowledge_points', type_='foreignkey')
    op.drop_column('knowledge_points', 'review_notes')
    op.drop_column('knowledge_points', 'review_status')
    op.drop_column('knowledge_points', 'aliases')
    op.drop_column('knowledge_points', 'topic_terms')
    op.drop_column('knowledge_points', 'canonical_title')
    op.drop_column('knowledge_points', 'source_document_id')
    op.drop_column('knowledge_points', 'primary_chapter_id')

    op.drop_table('document_section_mappings')
    op.drop_table('document_sections')
    op.drop_table('canonical_chapters')
