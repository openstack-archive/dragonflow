#!/usr/bin/python

import sys, getopt


def main(argv):
    db_ip = ''
    db_port = ''
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'd:t:i:p:', ['-d val', '-t val', '-i val', '-p val'])
    except getopt.GetoptError:
        print 'table_setup.py -d <driver>[ramcloud/rethinkdb] -t <table_name> -i <db_ip> -p <db_port>'
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
            print 'table_setup.py -d <driver>[ramcloud/rethinkdb] -t <table_name> -i <db_ip> -p <db_port>'
            sys.exit()
        elif opt in ("-d"):
            db_driver = arg
        elif opt in ("-t"):
            db_table = arg
        elif opt in ("-i"):
            db_ip = arg
        elif opt in ("-p"):
            db_port = arg

    print 'driver is: ', db_driver
    print 'table name is: ', db_table
    print 'db_ip  is: ', db_ip
    print 'db_port is: ', db_port

    if db_driver == "ramcloud":
        from dragonflow.db.drivers import ramcloud_nb_impl
        print 'driver for RamCloud'
        print 'DB Host ' + db_ip + ':' + db_port
        print 'Creating Table: ' + db_table
        client = ramcloud_nb_impl.RamcloudNbApi(db_ip, db_port)
        client.create_tables(db_table)
    elif db_driver == "rethinkdb":
        print 'driver for rethinkdb'
        print 'DB Host ' + db_ip + ':' + db_port
        import rethinkdb as R
        db_name = 'dragonflow'
        R.connect(host=db_ip, port=db_port).repl()
        db_exist = 0
        all_databases = R.db_list().run()
        for database in all_databases:
            if database == db_name:
                print 'Database ' + db_name + ' already exist, do not create'
                # R.db_drop(db_name).run()
                db_exist = 1
        if db_exist == 0:
            print 'Creating Database: ' + db_name
            R.db_create(db_name).run()

        all_tables = R.db(db_name).table_list().run()
        for table in all_tables:
            if table == db_table:
                print 'Table ' + db_table + ' already exist in database ' + db_name + '...cleaning up...'
                R.db(db_name).table_drop(db_table).run()
        print 'Creating Table: ' + db_table + ' in database: ' + db_name
        R.db(db_name).table_create(db_table, primary_key='name').run()


if __name__ == "__main__":
    main(sys.argv[1:])
