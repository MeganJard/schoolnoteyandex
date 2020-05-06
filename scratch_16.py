import json
import logging
import sqlite3

import requests
from flask import Flask, request
from flask import g

# инициализация приложения и БД
app = Flask(__name__)
DATABASE = 'db/database.db'
logging.basicConfig(level=logging.INFO, filename='app.log',
                    format='%(asctime)s %(levelname)s %(name)s %(message)s')


# три функции для работы с БД
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db


@app.teardown_appcontext  # именно из-за этой строки я поместил все функции после инициализации приложения)
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def query_db(query, args=(), one=True):
    with app.app_context():
        cur = get_db().execute(query, args)
        rv = cur.fetchall()
        cur.close()
        get_db().commit()
        return (str(rv[0][0]) if rv else None) if one else rv


# работа с геокодером
def getcoords(text):  # из текста - в координаты
    server = 'https://geocode-maps.yandex.ru/1.x'
    params = {
        'apikey': '40d1649f-0493-4b70-98ba-98533de7710b',
        'geocode': text,
        'format': 'json'
    }
    response = requests.get(server, params=params)
    return ','.join(
        response.json()["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"][
            'Point']['pos'].split())


# главный обработчик
def handle_dialog(res, req):
    res[
        'user_state_update'] = {}  # инициализация всех необходимых переменных для последующей удобной работы с ними
    res['session_state'] = {}
    res['response']['buttons'] = []
    if req['request']['command'] == 'rereg':  # команда для перерегистрации(нужна для отладки)
        res['user_state_update']['act'] = 'reg'
        res['user_state_update']['num'] = -2
        res['user_state_update']['role'] = 'null'
        res['response']['text'] = 'Пошла родная'
        return
    if 'user' in req['session']:  # проверка на авторизацию пользователя
        user_id = req['session']['user']['user_id']
        if req['session']['new'] and not req['state']['user']:  # если пользователь еще не заходил
            if (user_id,) not in query_db('select user_id from teachers', one=False) and (
                    user_id,) not in query_db('select user_id from pupils', one=False):
                res['response']['text'] = 'Вы учитель или ученик?'
                res['response']['buttons'] = [{'title': 'Учитель', 'hide': True},
                                              {'title': 'Ученик', "hide": True}]
                res['user_state_update']['num'] = -2
                return

        if req['state']['user'][
            'num'] == -2:  # проецесс регистрации, начинается без информации о роли пользователя...
            if 'учитель' in req['request']['nlu']['tokens']:
                res['user_state_update']['num'] = -1
                res['response']['text'] = 'Назовите секретное слово'
                res['user_state_update']['role'] = 'teacher'
                res['user_state_update']['act'] = 'reg'
                return
            elif 'ученик' in req['request']['nlu']['tokens']:
                res['user_state_update']['num'] = 0
                res['response'][
                    'text'] = 'Теперь необходимо зарегистрироваться\nКак Вас зовут?(ФИО)'
                res['user_state_update']['role'] = 'pupil'
                res['user_state_update']['act'] = 'reg'
                return
            else:
                res['user_state_update']['num'] = -2
                res['response']['text'] = 'Вы учитель или ученик?'
                return
        #Функционал учителя
        if req['state']['user']['role'] == 'teacher':

            if req['state']['user']['act'] == 'reg':  # ... и потом строится в зависимости от роли
                if req['request']['command'] == 'Отмена':
                    req['state']['user']['num'] = max(req['state']['user']['num'] - 1, 0)
                if req['state']['user']['num'] == -1:
                    if req['request']['command'] == 'Кванториум':
                        if not ((user_id,) in query_db('select user_id from teachers', one=False)):
                            query_db(f'insert into teachers(user_id) values("{user_id}")')
                        res['user_state_update']['num'] = 0
                        res['user_state_update']['act'] = 'reg'
                        res['response'][
                            'text'] = 'Теперь Вам необходимо зарегистрироваться\nКак Вас зовут (ФИО)?'
                        return

                    elif req['request']['command'] != 'Кванториум' or req['request'][
                        'command'] != 'Отмена':
                        res['user_state_update']['num'] = -1
                        res['response']['text'] = 'Назовите секретное слово'
                        return

                if req['state']['user']['act'] == 'reg':
                    if req['state']['user']['num'] == 0:
                        if len(req['request']['nlu']['entities']) == 1:
                            value = req["request"]["nlu"]["entities"][0]["value"]
                            try:

                                name = ' '.join([value['last_name'], value['first_name'],
                                                 value['patronymic_name']])
                                query_db(
                                    f'update teachers set FIO = "{name}" where user_id = "{user_id}"')
                                res['response'][
                                    'text'] = 'Назовите адрес Вашей школы (город, улица, дом)'
                                res['user_state_update']['num'] = 1
                            except Exception as ex:
                                res['response']['text'] = 'Как Вас зовут?'
                                res['user_state_update']['num'] = 0
                        else:
                            res['response']['text'] = 'Как Вас зовут?'
                            res['user_state_update']['num'] = 0
                            return
                    res['response']['buttons'].append({'title': 'Отмена', 'hide': True})
                    if req['state']['user']['num'] == 1:
                        try:
                            if req['request']['nlu']['entities'][0]['type'] == 'YANDEX.GEO':
                                value = req["request"]["nlu"]["entities"][0]["value"]
                                adr = ' '.join(
                                    [value['city'], value['street'], value['house_number']])
                                query_db(
                                    f'update teachers set school = "{getcoords(adr)}" where user_id = "{user_id}"')
                                res['response'][
                                    'text'] = 'Назовите предметы, которые Вы преподаете каждое одним словом в именительном падеже'
                                res['user_state_update']['num'] = 2
                            else:
                                res['response'][
                                    'text'] = 'Назовите адрес Вашей школы (город, улица, дом)'
                                res['user_state_update']['num'] = 1
                        except Exception as ex:
                            res['response'][
                                'text'] = 'Назовите адрес Вашей школы (город, улица, дом)' + str(ex)
                            res['user_state_update']['num'] = 1
                    if req['state']['user']['num'] == 2:
                        subj = (
                            'математика', 'история', 'физра', 'литература', 'немецкий',
                            'английский',
                            'французцский', 'алгебра', 'геометрия', 'география', 'обществознание',
                            'информатика', 'биология', 'химия', 'история', 'французский', 'физика',
                            'русский', 'программирование', 'робототехника')
                        answ = []
                        for i in req['request']['nlu']['tokens']:
                            if i in subj:
                                answ.append(i)
                        if len(answ):
                            if len(answ) > 1:
                                res['response'][
                                    'text'] = f'Отлично, ваши предметы - {", ".join(answ)}'
                            else:
                                res['response'][
                                    'text'] = f'Отлично, ваш предмет - {", ".join(answ)}'
                            query_db(
                                f'update teachers set subj = "{",".join(answ)}" where user_id = "{user_id}"')
                            res['user_state_update']['num'] = 3
                            res['response']['buttons'].append(
                                {'title': 'Продолжить', 'hide': True})
                        else:
                            res['response'][
                                'text'] = 'Назовите предметы, которые Вы преподаете в именительном падеже'
                            res['user_state_update']['num'] = 2
                    if req['state']['user']['num'] == 3:
                        res['response']['text'] = 'Вы успешно зарегистрировались!'
                        res['response']['buttons'].append({'title': 'Начать работу', 'hide': True})
                        res['user_state_update']['act'] = 'work'
                        res['user_state_update']['num'] = 0

            if req['state']['user'][
                'act'] == 'work':  # работа с уже зарегистрированным пользователем
                if 'workact' in req['state']['session']:
                    if req['state']['session']['workact'] == 'hwk':  # кейс обработки нового дз
                        if req['state']['user']['num'] == 0:
                            subj = query_db(
                                f'select subj from teachers where user_id ="{user_id}"').split(',')
                            if req['request']['command'].lower() in subj:
                                res['session_state']['subj'] = [req['request']['command'].lower()]
                                res['session_state']['workact'] = 'hwk'
                                res['user_state_update']['num'] = 1
                                res['response']['text'] = 'На какое число?'
                                return
                            else:
                                res['response']['text'] = 'Нет такого предмета'
                                res['response']['buttons'].append(
                                    {'title': 'Продолжить', 'hide': True})
                                return

                        if req['state']['user']['num'] == 1:
                            res['session_state']['subj'] = req['state']['session']['subj']
                            res['session_state']['workact'] = 'hwk'
                            res['response']['text'] = 'Проверка'
                            try:
                                if 'YANDEX.DATETIME' == req['request']['nlu']['entities'][1][
                                    'type']:
                                    if 'year' in req['request']['nlu']['entities'][1][
                                        'value'] and 'month' in \
                                            req['request']['nlu']['entities'][1][
                                                'value'] and 'day' in \
                                            req['request']['nlu']['entities'][1]['value']:

                                        fulldate = '.'.join([str(
                                            req['request']['nlu']['entities'][1]['value']['day']),
                                            str(req['request']['nlu']['entities'][
                                                    1]['value']['month']), str(
                                                req['request']['nlu']['entities'][1]['value'][
                                                    'year'])])
                                        res['session_state']['subj'].append(fulldate)
                                        res['response']['text'] = 'Продиктуйте или запишите задание'
                                        res['user_state_update']['num'] = 2
                                        return
                                    else:
                                        res['response']['text'] = 'Неправильный формат даты'
                                else:
                                    res['response']['text'] = 'Неправильный формат даты'
                            except Exception as ex:
                                res['response']['text'] = 'Неправильный формат даты'
                            res['response']['buttons'].append({'title': 'Продолжить', 'hide': True})
                            return
                        if req['state']['user']['num'] == 2:
                            res['session_state']['subj'] = req['state']['session']['subj']
                            res['session_state']['subj'].append(req['request']['command'])
                            res['session_state']['workact'] = 'hwk'
                            res['response']['text'] = 'Какой класс?'
                            res['user_state_update']['num'] = 3
                            return
                        if req['state']['user']['num'] == 3:
                            klasses = query_db(
                                f'select klasses from teachers where user_id="{user_id}"').split(
                                ',')
                            if req['request']['command'] in klasses:
                                homework = req['state']['session']['subj']
                                homework.append(req['request']['command'])
                                data = req['state']['session']['subj']
                                school = query_db(
                                    f'select school from teachers where user_id="{user_id}"')
                                klass = req['request']['command']
                                hwkfromdb = query_db(
                                    f'select homework from klasses where school="{school}" and klass="{klass}"')
                                hwkfromdb = eval(hwkfromdb) if str(hwkfromdb) != 'None' else []
                                n = -1
                                for i in range(len(hwkfromdb)):
                                    if hwkfromdb[i][0] == data[0] and hwkfromdb[i][1] == data[1]:
                                        n = i
                                if n != -1:
                                    del hwkfromdb[n]
                                hwkfromdb.append(data)
                                query_db(
                                    f'update klasses set homework="{str(hwkfromdb)}" where school="{school}" and klass="{klass}"')
                                res['response']['text'] = 'Задание добавлено'
                                res['response']['buttons'].append(
                                    {'title': 'Продолжить', 'hide': True})
                                return
                            else:
                                res['response']['text'] = 'Такого класса нет'
                                res['response']['buttons'].append(
                                    {'title': 'Продолжить', 'hide': True})
                                res['session_state']['subj'] = req['state']['session']['subj']
                                res['session_state']['workact'] = 'hwk'
                            return
                        # отловка непредвиденных ситуаций)
                        else:
                            res['response']['text'] = 'Промашка со счетчиком'
                            res['response']['buttons'].append({'title': 'Продолжить', 'hide': True})
                    # удаление обычного класса
                    if req['state']['session']['workact'] == 'duc':
                        klasses = query_db(
                            f'select klasses from teachers where user_id="{user_id}"')
                        klasses = list(klasses.split(',')) if klasses != "None" else []
                        if req['request']['command'] in klasses:
                            klasses.remove(klasses[klasses.index(req['request']['command'])])
                            res['response'][
                                'text'] = f'Вы удалили класс {req["request"]["command"]}'
                            klasses = ','.join(list(klasses))
                            res['response']['buttons'].append({"title": 'Продолжить', 'hide': True})
                            query_db(
                                f'update teachers set klasses="{klasses}" where user_id="{user_id}"')
                        else:
                            res['response']['text'] = 'Такого класса нет'
                            res['session_state']['workact'] = 'duc'
                    if req['state']['session']['workact'] == 'nuc':
                        if req['state']['user']['num'] == 0:
                            if req['request']['command'] in req['state']['session']['us_kl']:
                                res['response'][
                                    'text'] = f'Вы добавлили класс {req["request"]["command"]}'
                                klasses = query_db(
                                    f'select klasses from teachers where user_id="{user_id}"')
                                klasses = klasses + ',' + req["request"][
                                    "command"] if klasses != 'None' else req["request"]["command"]
                                query_db(
                                    f'update teachers set klasses="{klasses}" where user_id="{user_id}"')
                                res['response']['buttons'].append(
                                    {"title": 'Продолжить', 'hide': True})
                            else:
                                res['response']['text'] = 'Такого класса нет'
                                res['session_state']['workact'] = 'nuc'
                                res['session_state']['us_kl'] = req['state']['session']['us_kl']
                    if req['state']['session']['workact'] == 'keyred':
                        res['response'][
                            'text'] = f'Отлично, ваш новый ключ - {req["request"]["command"].lower()}'
                        res['response']['buttons'].append({'title': 'Продолжить', 'hide': True})
                        school = query_db(
                            f'select school from teachers where user_id="{user_id}"')
                        query_db(
                            f'update klasses set secret_word="{req["request"]["command"].lower()}" where school="{school}" and teacher="{user_id}"')
                    if req['state']['session']['workact'] == 'newklass':
                        if req['state']['user']['num'] == 0:
                            try:
                                if req['request']['nlu']['entities'][0][
                                    'type'] == 'YANDEX.NUMBER' and len(
                                    req['request']['nlu']['entities']) == 1 and len(
                                    req['request']['nlu']['tokens']) == 2 and len(
                                    req['request']['nlu']['tokens'][1]) == 1 and \
                                        req['request']['nlu']['tokens'][1] in 'абвгде':
                                    value = req['request']['nlu']['entities'][0]['value']
                                    letter = req['request']['nlu']['tokens'][1]
                                    school = query_db(
                                        f'select school from teachers where user_id="{user_id}"')
                                    li = query_db(
                                        f'select klass from klasses where school="{school}"')
                                    li = li if not (li is None) else []
                                    usl = str(value) + letter in li
                                    if usl:
                                        res['response'][
                                            'text'] = 'Нельзя зарегистрировать один и тот же класс дважды'
                                        res['session_state']['workact'] = 'newklass'
                                        return
                                    else:
                                        query_db(
                                            f'insert into klasses(klass, school, is_open, teacher) values("{str(value) + letter}", "{school}", "1", "{user_id}")')
                                        query_db(
                                            f'update teachers set klass="{str(value) + letter}" where user_id="{user_id}"')
                                        res['user_state_update']['num'] = 1
                                        res['session_state']['workact'] = req['state']['session'][
                                            'workact']
                                        res['response'][
                                            'text'] = 'Придумайте и запишите секретное слово строчными буквами\nОно необходимо для безопасности'
                                else:
                                    res['response'][
                                        'text'] = 'Кажется, Вы ничего не сказали про класс'
                                    res['session_state']['workact'] = 'newklass'
                            except Exception as ex:
                                res['response'][
                                    'text'] = 'Кажется, Вы ничего не сказали про класс' + str(ex)
                                res['session_state']['workact'] = 'newklass'
                        elif req['state']['user']['num'] == 1:
                            if (user_id,) in query_db('select teacher from klasses', one=False):
                                res['user_state_update']['num'] = 0
                                res['response']['text'] = ''
                            res['response'][
                                'text'] = f'Отлично, Вы зарегистрировали класс. Ваше секретное слово - {req["request"]["command"].lower()}'
                            query_db(
                                f'update klasses set secret_word="{req["request"]["command"].lower()}" where teacher="{user_id}"')
                            res['response']['buttons'].append({'title': 'Продолжить', 'hide': True})
                            res['user_state_update']['num'] = 0
                if not req['state']['session']:
                    res['user_state_update']['num'] = 0
                    res['response']['text'] = 'Личный кабинет'

                    if req['request'][
                        'command'] == 'Создать класс':  # Тут классный руководитель создает себе класс
                        if query_db(
                                f'select klass from teachers where user_id="{user_id}"') == 'None':
                            res['session_state']['workact'] = 'newklass'
                            res['response']['text'] = 'Скажите название класса\n(цифру и букву)'
                            return
                        else:
                            res['response']['text'] = 'Вы не можете изменить уже существующий класс'
                        return
                    elif req['request']['command'] == 'Редактировать ключ доступа':
                        res['session_state']['workact'] = 'keyred'
                        res['response']['text'] = 'Добавьте новый ключ доступа'
                        return
                    elif req['request']['command'] == 'Закрыть класс':
                        school = query_db(f'select school from teachers where user_id="{user_id}"')
                        def_val = None
                        query_db(
                            f'update klasses set is_open="{def_val}" where teacher="{user_id}" and school="{school}"')
                        res['response']['text'] = 'Вы закрыли класс'

                    elif req['request']['command'] == 'Открыть класс':
                        school = query_db(f'select school from teachers where user_id="{user_id}"')
                        def_val = '1'
                        query_db(
                            f'update klasses set is_open="{def_val}" where teacher="{user_id}" and school="{school}"')
                        res['response']['text'] = "Вы открыли класс"
                        res['response']['buttons'].append({'title': 'Продолжить', 'hide': 'True'})

                    elif req['request']['command'] == 'Классы':
                        klasses = query_db(
                            f'select klasses from teachers where user_id="{user_id}"')
                        klasses = klasses.split(',') if klasses != 'None' else ''
                        res['response']['text'] = '\n'.join(
                            klasses) if klasses != '' else 'У Вас пока нет классов'
                    elif req['request']['command'] == 'Добавить обычный класс':
                        my_klasses = query_db(
                            f'select klasses from teachers where user_id="{user_id}"')
                        my_klasses = set(my_klasses.split(',')) if my_klasses != 'None' else set()
                        school = query_db(f'select school from teachers where user_id="{user_id}"')
                        school_klasses = query_db(
                            f'select klass from klasses where school="{school}"', one=False)
                        school_klasses = set(
                            [i[0] for i in school_klasses]) if school_klasses != 'None' else set()
                        useful_klasses = school_klasses - my_klasses
                        if useful_klasses:
                            res['response'][
                                'text'] = 'Какой класс Вы хотите добавить?\n' + '\n'.join(
                                list(useful_klasses))
                            res['session_state']['workact'] = 'nuc'
                            res['session_state']['us_kl'] = list(useful_klasses)
                            return
                        else:
                            res['response']['text'] = 'Вы добавили все классы'
                    elif req['request']['command'] == 'Удалить обычный класс':
                        my_klasses = query_db(
                            f'select klasses from teachers where user_id="{user_id}"')
                        my_klasses = my_klasses.split(',') if my_klasses != "None" else ''
                        if my_klasses:
                            res['response']['text'] = 'Какой из них удалить:\n' + '\n'.join(
                                my_klasses)
                            res['session_state']['workact'] = 'duc'
                            return
                        else:
                            res['response'][
                                'text'] = 'У Вас пока что нет своих классов\nНо это легко исправить!'
                            res['response']['buttons'].append({'title': 'Продолжить'})

                    elif req['request']['command'] == 'Новое задание':
                        subj = query_db(
                            f'select subj from teachers where user_id = "{user_id}"').split(',')
                        if len(subj) > 1:
                            res['response']['text'] = 'Какой предмет?'
                        elif len(subj) == 1:
                            res['user_state_update']['num'] = 1
                            res['response']['text'] = 'На какое число какого года?'
                            res['session_state']['subj'] = subj
                        res['session_state']['workact'] = 'hwk'
                        return
                    else:
                        res['response']['text'] = 'Приятной работы!'
                        school = query_db(
                            f'select school from teachers where user_id="{user_id}"')
                        if query_db(
                                f'select secret_word from klasses where school="{school}" and teacher="{user_id}"') == 'None':
                            res['response']['text'] += '\nВам срочно нужно добавить ключ доступа!'

                    res['response']['buttons'] = [{'title': 'Новое задание', 'hide': True},

                                                  {'title': 'Классы', 'hide': True},
                                                  {'title': 'Редактировать ключ доступа',
                                                   'hide': True},
                                                  {'title': 'Добавить обычный класс', 'hide': True},
                                                  {'title': 'Удалить обычный класс', 'hide': True}]
                    if query_db(f'select * from klasses where teacher="{user_id}"'):
                        if query_db(
                                f'select is_open from klasses where teacher="{user_id}" ') == "None":
                            res['response']['buttons'].append(
                                {'title': 'Открыть класс', 'hide': True})
                        else:
                            res['response']['buttons'].append(
                                {'title': 'Закрыть класс', 'hide': True})
                    else:
                        res['response']['buttons'].insert(0,
                                                          {'title': 'Создать класс', 'hide': True})


        elif req['state']['user']['role'] == 'pupil':  # функционал ученика

            if req['state']['user']['act'] == 'reg':  # регистрация
                if req['request']['command'] == 'Отмена':
                    req['state']['user']['num'] = max(req['state']['user']['num'] - 1, 0)
                if req['state']['user']['num'] == 0:
                    if len(req['request']['nlu']['entities']) == 1:
                        value = req["request"]["nlu"]["entities"][0]["value"]
                        try:
                            name = ' '.join(
                                [value['last_name'], value['first_name'], value['patronymic_name']])
                            if not ((user_id,) in query_db('select user_id from pupils',
                                                           one=False)):
                                query_db(f'insert into pupils(user_id) values("{user_id}")')

                            query_db(
                                f'update pupils set FIO = "{name}" where user_id = "{user_id}"')
                            res['response'][
                                'text'] = 'Назовите адрес Вашей школы (город, улица, дом)'
                            res['user_state_update']['num'] = 1
                        except Exception as ex:
                            res['response']['text'] = 'Как Вас зовут?(ФИО)'
                            res['user_state_update']['num'] = 0
                            return
                    else:
                        res['response']['text'] = 'Как Вас зовут?(ФИО)'
                        res['user_state_update']['num'] = 0
                        return
                res['response']['buttons'].append({'title': 'Отмена', 'hide': True})
                if req['state']['user']['num'] == 1:
                    try:
                        if req['request']['nlu']['entities'][0]['type'] == 'YANDEX.GEO':
                            value = req["request"]["nlu"]["entities"][0]["value"]
                            adr = ' '.join([value['city'], value['street'], value['house_number']])
                            query_db(
                                f'update pupils set school = "{getcoords(adr)}" where user_id = "{user_id}"')
                            res['response'][
                                'text'] = 'Назовите класс и букву'
                            res['user_state_update']['num'] = 2
                        else:
                            res['response'][
                                'text'] = 'Назовите адрес Вашей школы (город, улица, дом)'
                            res['user_state_update']['num'] = 1
                    except Exception as ex:
                        res['response'][
                            'text'] = 'Назовите адрес Вашей школы (город, улица, дом)'
                        res['user_state_update']['num'] = 1
                if req['state']['user']['num'] == 2:
                    try:
                        if req['request']['nlu']['entities'][0]['type'] == 'YANDEX.NUMBER' and len(
                                req['request']['nlu']['entities']) == 1 and len(
                            req['request']['nlu']['tokens']) == 2 and len(
                            req['request']['nlu']['tokens'][1]) == 1 and \
                                req['request']['nlu']['tokens'][1] in 'абвгде':
                            value = req['request']['nlu']['entities'][0]['value']
                            letter = req['request']['nlu']['tokens'][1]
                            school = query_db(
                                f'select school from pupils where user_id = "{user_id}"')
                            if query_db(
                                    f'select school from klasses where klass = "{str(value) + letter}" and school = "{school}"'):
                                res['user_state_update']['num'] = 3
                                res['response']['text'] = 'Пожалуйста, назовите секретное слово'
                                res['session_state']['klass'] = str(value) + letter
                            else:
                                res['user_state_update']['num'] = 2
                                res['response'][
                                    'text'] = 'К сожалению, этот класс не зарегистрирован в системе\n Попросите вашего классного руководителя сделать это. ' + str(
                                    value) + letter + school
                    except Exception as ex:
                        res['response']['text'] = 'Кажется, Вы ничего не сказали про класс'
                if req['state']['user']['num'] == 3:
                    if 'klass' in req['state']['session']:
                        school = query_db(f'select school from pupils where user_id = "{user_id}"')
                        klass = req['state']['session']['klass']
                        is_open = query_db(
                            f'select is_open from klasses where klass="{klass}" and school="{school}"')
                        if req['request']['command'] == query_db(
                                f'select secret_word from klasses where school="{school}" and klass = "{klass}"') and is_open == '1':
                            pupils = query_db(
                                f'select pupils from klasses where klass = "{klass}" and school = "{school}"')
                            stringa = pupils.split(',') if pupils else []
                            stringa.append(user_id)
                            call = ','.join(stringa)
                            query_db(
                                f'update klasses set pupils=("{call}") where school="{school}" and klass = "{klass}"')
                            query_db(f'update pupils set klass="{klass}" where user_id="{user_id}"')
                            res['user_state_update']['num'] = 0
                            res['user_state_update']['act'] = 'work'
                            res['response']['text'] = 'поздравляем с регистрацией!'
                            res['response']['buttons'].append(
                                {'title': 'Начать работу', 'hide': True})
                        else:
                            res['response']['text'] = 'Неверно! Попробуйте еще раз.'
                    else:
                        res['response'][
                            'text'] = 'Я уже успела забыть про Ваш класс\nМожете напомнить?'
                        res['user_state_update']['num'] = 2
            elif req['state']['user']['act'] == 'work':  # работа после регистрации
                if req['state']['session']:
                    if 'workact' in req['state']['session']:
                        if 'wh' == req['state']['session']['workact']:  # просомтр дз из БД
                            klass = query_db(f'select klass from pupils where user_id="{user_id}"')
                            school = query_db(
                                f'select school from pupils where user_id="{user_id}"')
                            if req['state']['user']['num'] == 0:
                                subj = query_db(
                                    f'select homework from klasses where school="{school}" and klass="{klass}"')
                                subj = set([i[0] for i in eval(subj)]) if subj != 'None' else set()
                                if req['request']['command'] in subj:
                                    res['response']['text'] = 'Какое число?'
                                    res['session_state']['subj'] = req['request']['command']
                                    res['user_state_update']['num'] = 1
                                    res['session_state']['workact'] = 'wh'
                                else:
                                    res['response']['text'] = 'На этот предмет нет домашних заданий'
                                    res['response']['buttons'].append(
                                        {'title': 'Продолжить работу'})
                            if req['state']['user']['num'] == 1:
                                try:
                                    if 'YANDEX.DATETIME' == req['request']['nlu']['entities'][1][
                                        'type']:
                                        if 'year' in req['request']['nlu']['entities'][1][
                                            'value'] and 'month' in \
                                                req['request']['nlu']['entities'][1][
                                                    'value'] and 'day' in \
                                                req['request']['nlu']['entities'][1][
                                                    'value']:

                                            fulldate = '.'.join(
                                                [str(req['request']['nlu']['entities'][1]['value'][
                                                         'day']),
                                                 str(req['request']['nlu']['entities'][1]['value'][
                                                         'month']), str(
                                                    req['request']['nlu']['entities'][1]['value'][
                                                        'year'])])
                                            subj = query_db(
                                                f'select homework from klasses where school="{school}" and klass="{klass}"')
                                            subj = eval(subj) if subj != 'None' else []
                                            for i in subj:
                                                if i[0] == req['state']['session']['subj'] and i[
                                                    1] == fulldate:
                                                    res['response']['text'] = i[2]
                                                    res['response']['buttons'].append(
                                                        {'title': 'Продолжить', 'hide': True})
                                                    return
                                            res['response'][
                                                'text'] = 'На это число нет заданий по этому предмету'
                                        else:
                                            res['response']['text'] = 'Неправильный формат даты'
                                    else:
                                        res['response']['text'] = 'Неправильный формат даты'
                                except Exception as ex:
                                    res['response']['text'] = 'Неправильный формат даты' + str(ex)
                        else:
                            res['response']['text'] = 'Пролет с условием)'
                else:
                    if req['request']['command'] == 'Просмотреть задание':
                        res['session_state']['workact'] = 'wh'
                        res['response']['text'] = 'Какой предмет?'
                        return
                    res['user_state_update']['num'] = 0
                    res['response']['text'] = 'Личный кабинет'
                    res['response']['buttons'].append({'title': 'Просмотреть задание'})



    # появится, если юзер на авторизован в Яндексе
    else:
        res['response']['text'] = 'Вам необходимо зарегистрироваться в Яндексе, чтобы продолжить'


@app.route('/post', methods=['POST'])
def main():
    logging.info('Request: %r', request.json)
    response = {
        'session': request.json['session'],
        'version': request.json['version'],
        'response': {
            'end_session': False
        }
    }
    handle_dialog(response, request.json)
    logging.info('Request: %r', response)
    return json.dumps(response)


if __name__ == '__main__':
    app.run()
