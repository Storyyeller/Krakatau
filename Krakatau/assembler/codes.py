_handle_types = 'getField getStatic putField putStatic invokeVirtual invokeStatic invokeSpecial newInvokeSpecial invokeInterface'.split()
handle_codes = dict(zip(_handle_types, range(1,10)))

newarr_codes = dict(zip('boolean char float double byte short int long'.split(), range(4,12)))