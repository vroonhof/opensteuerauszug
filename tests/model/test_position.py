import pytest
from opensteuerauszug.model.position import SecurityPosition

def test_security_position_equality_and_hash():
    a = SecurityPosition(depot='D1', valor='123', isin='ISIN1', symbol='SYM', securityType='A', description='desc1')
    b = SecurityPosition(depot='D1', valor='123', isin='ISIN1', symbol='SYM', securityType='B', description='desc2')
    c = SecurityPosition(depot='D1', valor='123', isin='ISIN1', symbol='SYM', securityType=None, description=None)
    d = SecurityPosition(depot='D1', valor='123', isin='ISIN1', symbol='DIFF', securityType='A', description='desc1')

    # a, b, c should be equal, d should not
    assert a == b
    assert a == c
    assert b == c
    assert a != d
    # Hashes should match for a, b, c
    assert hash(a) == hash(b) == hash(c)
    # d should have a different hash
    assert hash(a) != hash(d)
    # Test dict usage
    dct = {a: 1}
    dct[b] = 2  # Should overwrite
    assert dct[a] == 2
    dct[c] = 3  # Should overwrite
    assert dct[a] == 3
    dct[d] = 4
    assert dct[d] == 4 