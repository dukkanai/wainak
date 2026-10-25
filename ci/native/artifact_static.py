"""Portable structural inspection only; no Apple tools, linker or runtime calls."""
import re
import struct
from check_static import require, read_regular


def static_arm64_container_bytes(data):
    require(isinstance(data,(bytes,bytearray)), 'native archive bytes required')
    data=bytes(data)
    require(len(data)>=8,'truncated native archive')
    if data[:8]==b'!<arch>\n':
        return 'thin-static-ar'
    formats={b'\xca\xfe\xba\xbe':('>',False),b'\xbe\xba\xfe\xca':('<',False),
             b'\xca\xfe\xba\xbf':('>',True),b'\xbf\xba\xfe\xca':('<',True)}
    require(data[:4] in formats,'native binary is neither static ar nor supported FAT')
    endian,wide=formats[data[:4]]; count=struct.unpack_from(endian+'I',data,4)[0]
    require(count==1,'only one arm64 architecture is allowed per platform slice')
    width=32 if wide else 20; end=8+count*width
    require(len(data)>=end,'truncated FAT table')
    spans=[]
    for index in range(count):
        if wide:
            cpu,subtype,offset,size,align,reserved=struct.unpack_from(endian+'IIQQII',data,8+index*width)
            require(reserved==0,'nonzero FAT64 reserved field')
        else:
            cpu,subtype,offset,size,align=struct.unpack_from(endian+'IIIII',data,8+index*width)
        require(cpu==0x0100000c and subtype&0x00ffffff==0,'only generic arm64 static slices are allowed')
        require(align<=30 and offset%(1<<align)==0,'invalid FAT alignment')
        require(offset>=end and size>=8 and offset+size==len(data),'invalid FAT bounds')
        require(all(offset+size<=a or b<=offset for a,b in spans),'overlapping FAT entries')
        require(data[offset:offset+8]==b'!<arch>\n','FAT payload is not a static ar archive')
        spans.append((offset,offset+size))
    return 'fat64-static-ar' if wide else 'fat-static-ar'


def static_arm64_container(path):
    return static_arm64_container_bytes(read_regular(path,256*1024*1024))


def validate_modulemap(text, headers):
    tokens=re.findall(r'"[^"\n]*"|[A-Za-z_]+|[{}*]',text)
    remainder=re.sub(r'"[^"\n]*"|[A-Za-z_]+|[{}*]|\s','',text)
    expected=['framework','module','"Archivebridge"','{']
    for header in headers: expected.extend(['header','"'+header+'"'])
    expected.extend(['export','*','}'])
    require(not remainder and tokens==expected,'unexpected framework module-map semantics')


def validate_apple_load_commands(text, variant):
    """At least one actual platform record, no conflicting records; not all members."""
    require(variant in ('device','simulator'),'invalid requested Apple variant')
    expected=2 if variant=='device' else 7
    mapping={'2':2,'7':7,'IOS':2,'IOSSIMULATOR':7,'PLATFORMIOS':2,'PLATFORMIOSSIMULATOR':7}
    platforms=[]; minimums=[]; legacy=0
    for block in re.split(r'(?m)^\s*Load command \d+\s*$',text):
        command=re.search(r'(?m)^\s*cmd\s+(LC_[A-Z_]+)\s*$',block)
        if not command: continue
        name=command.group(1)
        if name=='LC_BUILD_VERSION':
            raw=re.search(r'(?m)^\s*platform\s+([A-Za-z0-9_]+)\s*$',block)
            minimum=re.search(r'(?m)^\s*minos\s+(\d+(?:\.\d+){1,2})\s*$',block)
            require(raw is not None and minimum is not None,'malformed Apple build-version record')
            value=mapping.get(raw.group(1).upper().replace('_',''))
            require(value==expected,'actual Mach-O platform conflicts with slice metadata')
            platforms.append(value);minimums.append(minimum.group(1))
        elif name.startswith('LC_VERSION_MIN_'):
            require(name=='LC_VERSION_MIN_IPHONEOS','foreign legacy minimum-OS record')
            minimum=re.search(r'(?m)^\s*version\s+(\d+(?:\.\d+){1,2})\s*$',block)
            require(minimum is not None,'malformed legacy minimum-OS record')
            minimums.append(minimum.group(1));legacy+=1
    require(platforms,'no actual LC_BUILD_VERSION platform evidence')
    require(minimums and all(v in ('15.0','15.0.0') for v in minimums),'actual Mach-O minimum iOS is not15')
    return {'platform_id':expected,'platform_record_count':len(platforms),
            'legacy_minimum_record_count':legacy,'minimums':sorted(set(minimums)),
            'all_archive_members_platform_proven':False}
