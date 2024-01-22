#! /bin/bash

echo "Generating ZIP test files"
cp bad_zip.txt bad_zip.zip
cd archive
zip ../archive.zip *
cd ../tree
zip ../archive_with_tree.zip -r *
cd ..
echo "ZIP test files generated"
