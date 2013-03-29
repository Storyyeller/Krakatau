def get_attribute_raw(bytestream):
    name_ind, length = bytestream.get('>HL')
    data = bytestream.getRaw(length)
    return name_ind,data

def get_attributes_raw(bytestream):
    attribute_count = bytestream.get('>H')
    return [get_attribute_raw(bytestream) for _ in range(attribute_count)]

def fixAttributeNames(attributes_raw, cpool):
    return [(cpool.getArgsCheck('Utf8', name_ind), data) for name_ind, data in attributes_raw]
