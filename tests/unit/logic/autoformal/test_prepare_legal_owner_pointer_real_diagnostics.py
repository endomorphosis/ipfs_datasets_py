from copy import deepcopy
import pytest
from scripts.ops.legal_ir import prepare_legal_owner_pointer_real_diagnostics as p


def document(text='Office shall file within ten days after receipt.'):
    return {'document_text':text,'document_text_sha256':p.sha(text),'document_id':'doc-one','html_sha256':'a'*64,
            'legal_id':'authored:test','edition':2024,'source_url':'https://example.invalid/fixture',
            'paragraphs':[{'paragraph_index':0,'kind':'codified_body','text':text,'text_sha256':p.sha(text),
                           'char_start':0,'char_end':len(text),'subsection_path':'(a)'}]}


def test_complete_paragraph_and_context_identity_separate_from_query():
    d=document();q,proof=p.extract(d,0,'within ten days after receipt')
    assert set(q)==p.metrics.SOURCE_KEYS and q['source_text']==d['document_text']
    assert proof['edition']==2024 and proof['complete_paragraph_used'] and not proof['full_document_supplied_to_model']
    assert not proof['independent_gold'] and not proof['owner_reference_supplied']


@pytest.mark.parametrize('mutation',[lambda d:d.update(document_text_sha256='0'*64),
    lambda d:d['paragraphs'][0].update(char_start=1),lambda d:d['paragraphs'][0].update(kind='editorial_note')])
def test_repaired_local_reference_cannot_override_parent_document(mutation):
    d=document();mutation(d)
    with pytest.raises(ValueError):p.extract(d,0,'within ten days after receipt')


def test_overlength_is_explicitly_unsupported_never_truncated():
    text=' '.join(['word']*260)+' within ten days after receipt.'
    q,proof=p.extract(document(text),0,'within ten days after receipt')
    assert q['source_text']==text and not proof['within_model_source_budget'] and not proof['context_truncated']


def test_duplicate_time_literal_requires_explicit_occurrence_disambiguation():
    with pytest.raises(ValueError):p.extract(document('within ten days then within ten days'),0,'within ten days')
