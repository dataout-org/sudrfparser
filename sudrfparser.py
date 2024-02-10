from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException,WebDriverException,TimeoutException
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import requests
import json
import re
import base64
from IPython.display import Image
import time
import os
from os import listdir
from os.path import isfile, join
from collections import Counter
import gzip

###
# Functions to parse criminal cases of the first instance from websites of federal courts of general jurisdiction hosted on sudrf.ru
# Uses Chrome driver
# Developed by Dataout.org
# CC-BY-SA 4.0
###


def _set_browser(path_to_driver:str,imagesOff=False,javaScriptOff=False):
    '''
    Setting up a driver with the optional parameters to turn off images and javascript (which might be helpful in speeding up parsing);
    path_to_driver: str, path to Chrome driver;
    imagesOff: bool, False to load images, True to ignore images; default False;
    javaScriptOff: bool, False to load javaScript, True to ignore javaScript; default False;
    Make sure to install the corresponding Chrome webdriver from 'https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json' (choose the platform and version that matches the version of your Google Chrome browser); after downloading, unzip and copy the path to the driver used for 'path_to_driver';
    '''

    chrome_options = Options()

    # preferences
    prefs = {'profile.managed_default_content_settings.javascript': 1,
    'profile.managed_default_content_settings.images': 1}

    # turn off images
    if imagesOff == True:
        prefs['profile.managed_default_content_settings.images'] = 2
    
    # turn off JavaScript
    if javaScriptOff == True:
        prefs['profile.managed_default_content_settings.javascript'] = 2

    chrome_options.add_experimental_option("prefs", prefs)

    browser = webdriver.Chrome(executable_path=path_to_driver,options=chrome_options)

    return browser

def _explicit_wait(browser,by:str,element:str,sec:int) -> bool:
    '''
    Sets explicit browser wait for presence of an element by ID or CLASS_NAME
    browser: selenium.webdriver.chrome.webdriver.WebDriver (the output of '_set_browser')
    by: str, "ID" or "CLASS_NAME";
    element: str, ID or CLASS_NAME of an element to wait for
    sec: int, max waiting time in sec
    returns True if the element is found, False otherwise
    '''
    try:
        if by == 'ID':
            element = WebDriverWait(browser,sec).until(EC.presence_of_element_located((By.ID, element)))
            if element:
                element_found = True

        if by == 'CLASS_NAME':
            element = WebDriverWait(browser,sec).until(EC.visibility_of_element_located((By.CLASS_NAME, element)))
            if element:
                element_found = True
    except:
        element_found = False
        
    return element_found

def get_courts_list(path_to_driver:str) -> dict:
    '''
    Getting all courts websites from 'https://sudrf.ru/index.php?id=300'
    Using the static file with region codes "rf_region_codes.json" on Dataout GitHub
    path_to_driver: str, path to Chrome driver
    Returns dict {"region_code": [
                    {"court_id": "",
                    "court_name": "",
                    "court_website": ""}]
    '''

    # reading region codes
    region_codes_url = "https://raw.githubusercontent.com/dataout-org/sudrfparser/main/courts_info/rf_region_codes.json"
    r = requests.get(region_codes_url)
    region_codes = r.json()
        
    browser = _set_browser(path_to_driver)

    # static uri with a list of courts
    bsr_courts = "https://sudrf.ru/index.php?id=300&act=go_search&searchtype=fs"
    
    all_courts_dict = {}

    for code in region_codes.keys():
        #updating url
        url = f'{bsr_courts}&court_subj={code}'
        #opening a page
        browser.get(url)
        #wait for search results to load
        el = _explicit_wait(browser,"CLASS_NAME","search-results",6)
        #converting a page to soup
        soup = BeautifulSoup(browser.page_source, 'html.parser')

        list_of_courts = []

        for li in soup.find("ul", {"class": "search-results"}).find_all("li"):

            court_id = li.find("a")["onclick"].split(",")[-1].replace(")","").replace("'","").replace(";","")

            court_data = {}
            court_data["court_id"] = court_id

            for i in li.div.find_all("a"):
                if len(i.contents) > 0 and 'http' in i.contents[0]:
                    court_data["court_name"] = li.a.contents[0]
                    court_data["court_website"] = i.contents[0]

            list_of_courts.append(court_data)
            
        all_courts_dict[code] = list_of_courts
        
    browser.close()
    
    return all_courts_dict

def _get_form_type(soup) -> str:
    '''
    Checking the search form type used on a court website; form2 uses JavaScript, form1 doesn't;
    Takes a soup of a page with a search form
    Returns str 'form1' or 'form2'
    '''

    content = soup.find("div", {"id": "modSdpContent"})

    if content != None:
        if content.find("link") == None:
            form_type = 'form1'
        else:
            form_type = 'form2'
    else:
        form_type = 'other'

    return form_type

def _check_form_and_captcha(soup) -> dict:
    '''
    Checking if there's a captcha on a website and which form type the website has to define parsing scenarios
    Takes a soup of a page with a search form
    Returns a dict per website: {website:{"form_type":"","captcha":""}}
    '''

    dict_per_site = {}

    # checking form type
    form_type = _get_form_type(soup)
    dict_per_site["form_type"] = form_type

    # conditions for the form type and module part
    if form_type == "form1" or form_type == "form2":
        box_common = soup.find("div", {"class": "box box_common m-all_m"})
        if box_common != None:
            if "Проверочный код" in box_common.text:
                dict_per_site["captcha"] = "True"
            else:
                dict_per_site["captcha"] = "False"
    else:
        dict_per_site["form_type"] = "other"
        dict_per_site["captcha"] = "False"

    return dict_per_site

### Form1 functionality ###

def _num_cases_pages_f1(soup) -> tuple:
    """
    Takes a soup of a page with search results
    Getting N of the found cases and pages on one website with 'form1'
    Returns a tuple with int (for example, (247,10)), where the first value is N cases, the second is N pages
    """
    # number of cases
    num_cases_str = soup.find("div", {"id": "content"}).find("table").find("td", {"align":"right"}).text
    num_cases = int(re.search('\d+\.',num_cases_str)[0].rstrip("."))

    # number of pages
    # form1 always displays 25 cases per page
    if num_cases % 25 > 0:
        num_pages = num_cases // 25 + 1
    else:
        num_pages = int(num_cases / 25)
    
    return num_cases, num_pages

def _get_cases_ids_per_page_f1(soup) -> list:
    """
    Takes a soup of a page with search results
    Parsing cases ids and uids from the search results table on one page of one website with 'form1'
    Return a list of strings, for example ['case_id=16520648&case_uid=e061150b-c482-4598-8aaf-e4ef9d949936']
    """
    table_rows = soup.find("table", {"id": "tablcont"}).find_all("tr")
    ids = []
    
    for row in table_rows:
        # taking only the first column
        first_cell = row.find("td")
        if first_cell != None:
            case_link = first_cell.find("a")['href']
            case_id_str = re.search('case_id=\d*&case_uid=.*&',case_link)[0].rstrip('&')
            ids.append(case_id_str)
            
    return ids

def _get_one_case_text_f1(soup) -> dict:
    '''
    Takes a soup of a page with case metadata
    Returns a dict with case metadata and decision text if present
    '''

    results = {}
    metadata = {}
    results["case_text"] = ""
    metadata["accused"] = []

    content = soup.find('div', {'class': 'contentt'})

    ### checking if the internal case ID is present 
    ### 
    id_text = soup.find('div', {'class': 'casenumber'})
    if id_text != None:
        metadata["id_text"] = id_text.text.replace('\n',"").replace('\t',"")
    else:
        metadata["id_text"] = ""
    ###
    
    ### checking if there's any content
    ###
    if content != None:
        
        results["case_found"] = "True"

        ### case decision text
        ###
        # checking tabs
        tabs = soup.find("ul", class_="tabs").find_all("li")

        for tab in tabs:
            # getting the tab ID with the case text 
            if " АКТЫ" in tab.text:
                tab_id = tab.attrs['id'].replace('tab','cont')
                results["case_text"] = content.find('div',{'id':tab_id}).text.replace('"','\'').replace('\xa0','')

            ### accused info: names and articles
            ###
            if 'ЛИЦА' in tab.text:
                accused_list = []
                tab_id = tab.attrs['id'].replace('tab','cont')
                accused_content = content.find('div',{'id':tab_id}).find_all('tr')
                for tr in accused_content[2:]:
                    accused_list.append({'name':tr.find_all('td')[0].text,\
                                        'article':tr.find_all('td')[1].text.rstrip('УК РФ').split(';')})
                metadata["accused"] = accused_list
            ###
        ###

        ### case metadata
        ###
        metadata_1 = content.find('div', {'id': 'cont1'})
    
        for tr in metadata_1.find('table').find_all('tr'):
            # another case identifier
            if 'идентификатор' in tr.text:
                metadata["uid_2"] = tr.find_all('td')[-1].text
            # receipt date
            if 'Дата поступления' in tr.text:
                metadata["adm_date"] = tr.find_all('td')[-1].text
            # judge
            if 'Судья' in tr.text:
                metadata["judge"] = tr.find_all('td')[-1].text
            # case status
            if 'Результат' in tr.text:
                metadata["decision_result"] = tr.find_all('td')[-1].text
        ###   

        results["metadata"] = metadata
        
    else:
        results["case_found"] = "False"

    return results


def _get_autocaptcha(apikey:str,base64Image:str) -> str:
    '''
    Getting the captcha value automatically using OCR API from https://ocr.space/OCRAPI
    apikey: str, API key provided by https://ocr.space/OCRAPI;
    base64Image: str, captcha image data;
    Returns str
    '''

    auto_captcha = ""

    img_data = f"data:image/jpeg;base64,{base64Image}"

    params = {"apikey": apikey, "OCREngine":"2", "base64Image":img_data}
    r = requests.post('https://api.ocr.space/parse/image',data=params)
    parsed = r.json()

    # parsed successfully
    if parsed['IsErroredOnProcessing'] == False:
        if parsed.get('ParsedResults') != None:
            auto_captcha = parsed['ParsedResults'][0]['ParsedText']

    return auto_captcha


def _get_captcha_f1(browser,website:str,autocaptcha="") -> str:
    '''
    Getting captcha code of form1 and displaying it; requires user's input;
    browser: selenium.webdriver.chrome.webdriver.WebDriver (the output of '_set_browser');
    website: str, website address;
    autocaptcha: str, API key from https://ocr.space/OCRAPI to guess captcha automatically, default '';
    Returns str, an addition to the link with captcha code;
    '''
    page_with_code = website + "/modules.php?name=sud_delo&srv_num=1&name_op=sf&delo_id=1540005"

    tries = 0

    while tries <= 3:

        browser.get(page_with_code)
        # checking if the search form is present
        check_content = _explicit_wait(browser,"ID","content",6)

        # form is present, getting captcha code
        if check_content == True:

            soup = BeautifulSoup(browser.page_source, 'html.parser')
            # finding the first table in the form
            content = soup.find("div", {"id": "content"}).find("table")
            # getting captcha ID
            captcha_id = content.find("input", {"name": "captchaid"})["value"]

            imgstring = content.find("img")["src"].split(",")[1]
            imgdata = base64.b64decode(imgstring)

            # checking if API key is present for autorecognition of captcha
            if autocaptcha != "":
                captcha_guessed = _get_autocaptcha(autocaptcha,imgstring)

                # failed, enter captcha manually
                if captcha_guessed == "":

                    print("Autorecognition of captcha failed. Enter captcha manually")
                    # enlarging the captcha image
                    display(Image(imgdata, width=400, height=200))
                    # entering captcha manually
                    captcha_guessed = input("Enter captcha: ")

            # if no API key
            else:
                # enlarging the captcha image
                display(Image(imgdata, width=400, height=200))
                # entering captcha manually
                captcha_guessed = input("Enter captcha: ")

            captcha_addition = f"&captcha={captcha_guessed}&captchaid={captcha_id}"

            # success, stop trying
            break

        # failed to retrieve captcha
        else:
            tries += 1
            captcha_addition = ""
            # try again
            continue
            
    return captcha_addition

def _get_cases_texts_f1(website:str, region:str, start_date:str, end_date:str, path_to_driver:str, srv_num=['1'], path_to_save='', captcha=False, autocaptcha="") -> dict:
    '''
    Getting all court cases on one website in the indicated date range
    website: str, website address;
    region: str, region code;
    Dates to indicate a date range in which to look for cases:
    (for example, the range 01.01.2021 and 31.12.2021 will get all the cases registered in a court in 2021)
        start_date: str, date of cases registration in a court, 'DD.MM.YYYY';
        end_date: str, date of cases registration in a court, 'DD.MM.YYYY';
    path_to_driver: str, path to Chrome driver;
    srv_num: list, servers where to look for cases, default ['1']; one website can have multiple servers with criminal cases of the first instance;
    path_to_save: str, path where to save the results, default '' (the same directory of the script execution);
    captcha: bool, if a website has captcha protection, default False; automatically checks if captcha is present, and if it's present: (1) a user will be asked to solve it or (2) if a user has API key from https://ocr.space/OCRAPI to guess captcha automatically, the captcha will be autorecognised;
    autocaptcha: str, API key from https://ocr.space/OCRAPI to guess captcha automatically, default ''; 
    Saves json files with all parsed cases per website's server (for example, if there are 2 servers on one website, there will be 2 json files); Logs errors and pages that were not parsed;
    Returns a dict with info about N cases found per server
    '''

    # turn off JavaScript and images for form1
    browser = _set_browser(path_to_driver,imagesOff=True,javaScriptOff=True)

    year = start_date.split('.')[-1]
    return_dict = {website:{"year":year,"n_cases_by_server":{}}}

    # Iterating over servers
    for server in srv_num:

        results_per_site = {}
        results_per_site[website] = {}
        num_cases = 0
        list_of_cases = []
        logs = {}

        module_form1 = f'/modules.php?name=sud_delo&srv_num={server}&name_op=r&delo_id=1540006&case_type=0&new=0&u1_case__ENTRY_DATE1D={start_date}&u1_case__ENTRY_DATE2D={end_date}&delo_table=u1_case&U1_PARTS__PARTS_TYPE='

        link_to_site = website + module_form1

        # checking captcha
        if captcha == True:
            captcha_addition = _get_captcha_f1(browser,website,autocaptcha)
            link_to_site += captcha_addition

        # try to load the website content 3 times
        tries = 0

        while tries <= 3:
            try:
                browser.get(link_to_site)
                # explicitly waiting for the results table
                el_found = _explicit_wait(browser,"ID","tablcont",6)

                # if there is a table with results
                if el_found == True:

                    soup = BeautifulSoup(browser.page_source, 'html.parser')

                    stats = _num_cases_pages_f1(soup)
                    num_cases = stats[0]
                    num_pages = stats[1]

                    logs["cases_found"] = "True"
                    logs["driver_error"] = "False"
                    logs["pagination_error"] = []
                    results_per_site[website]["num_cases"] = num_cases

                    # getting cases on the first page
                    # this will be all the cases for 1 page results
                    # first, getting all the cases ids on the page
                    cases_ids_on_page = _get_cases_ids_per_page_f1(soup)

                    # iterating over cases and colecting texts
                    for case_id in cases_ids_on_page:

                        case_page = f"{website}/modules.php?name=sud_delo&srv_num={server}&name_op=case&{case_id}&delo_id=1540006"
                        browser.get(case_page)
                        soup_case = BeautifulSoup(browser.page_source, 'html.parser')

                        # getting case data
                        results_per_case = _get_one_case_text_f1(soup_case)
                        results_per_case["case_id_uid"] = case_id
                        list_of_cases.append(results_per_case)

                    if num_pages > 1:

                        for i in range(2,num_pages+1):
                            page_addition = f'&page={i}'
                            link_with_page = link_to_site + page_addition

                            # adding Exception in case of the driver error
                            try:
                                browser.get(link_with_page)
                                soup = BeautifulSoup(browser.page_source, 'html.parser')

                                # checking if session is expired when captcha is True
                                if captcha == True and soup.find("div", {"id": "error"}):
                                    # getting new captcha
                                    captcha_addition = _get_captcha_f1(browser,website,autocaptcha)
                                    link_to_site = website + module_form1 + captcha_addition
                                    link_with_page = link_to_site + page_addition
                                    browser.get(link_with_page)
                                    soup = BeautifulSoup(browser.page_source, 'html.parser')

                                # if there's no table content found
                                if soup.find("table", {"id": "tablcont"}) == None:
                                    logs['pagination_error'].append(i)

                                # if everything's ok
                                if soup.find("table", {"id": "tablcont"}):

                                    cases_ids_on_page = _get_cases_ids_per_page_f1(soup)

                                    for case_id in cases_ids_on_page:
                                        case_page = f"{website}/modules.php?name=sud_delo&srv_num={server}&name_op=case&{case_id}&delo_id=1540006"
                                        browser.get(case_page)
                                        soup_case = BeautifulSoup(browser.page_source, 'html.parser')

                                        # getting case data
                                        results_per_case = _get_one_case_text_f1(soup_case)
                                        results_per_case["case_id_uid"] = case_id
                                        list_of_cases.append(results_per_case)

                            except WebDriverException:
                                # recording the N of page that couldn't be loaded
                                logs["driver_error"] = "True"
                                logs["pagination_error"].append(i)
                                # continue to the next page
                                continue

                    # saving data                
                    results_per_site[website]["cases"] = list_of_cases
                    results_per_site[website]["logs"] = logs

                    # results are saved, stop trying, break the while loop
                    break

                # no cases found (no results or error)
                else:
                    tries += 1

                    logs["cases_found"] = "False"
                    logs["driver_error"] = "False"
                    logs["pagination_error"] = []
                    results_per_site[website]["num_cases"] = num_cases
                    results_per_site[website]["cases"] = list_of_cases
                    results_per_site[website]["logs"] = logs
                    
                    #try again
                    continue


            except WebDriverException:
                tries += 1

                logs["cases_found"] = "False"
                logs["driver_error"] = "True"
                logs["pagination_error"] = []
                results_per_site[website]["num_cases"] = num_cases
                results_per_site[website]["cases"] = list_of_cases
                results_per_site[website]["logs"] = logs

                #try again
                continue

        file_name = f"{path_to_save}{region}_{website.replace('http://','').replace('.sudrf.ru','').replace('.','_').replace('/','')}_{server}_{year}.json"

        with open(file_name, 'w') as jf:
            json.dump(results_per_site, jf, ensure_ascii=False)

        return_dict[website]["n_cases_by_server"][server] = num_cases

    browser.close()

    return return_dict


### Form2 functionality ###

def _num_cases_pages_f2(soup) -> tuple:
    """
    Takes a soup of a page with search results
    Getting N of the found cases and pages on one website with 'form2'
    Returns a tuple with int (for example, (247,10)), where the first value is N cases, the second is N pages
    """
    # number of cases
    num_cases_str = soup.find("div", {"class": "lawcase-count"}).text
    num_cases = int(re.search('найдено - \d*',num_cases_str)[0].split('- ')[1])
    
    # in form2, there can be different N of cases per page
    pages_range = int(re.search('с \d по \d*',num_cases_str)[0].split(' ')[-1])

    # number of pages
    if num_cases % pages_range > 0:
        num_pages = num_cases // pages_range + 1
    else:
        num_pages = int(num_cases / pages_range)
    
    return num_cases, num_pages

def _get_cases_ids_per_page_f2(soup) -> list:
    """
    Takes a soup of a page with search results
    Parsing cases ids and uids from the search results table on one page of one website with 'form2'
    Return a list of strings, for example ['_uid=159bf2f8-93a2-40f6-b694-8616dbabb3b3']
    """
    case_rows = soup.find_all("td",{"class":"lawcase-number-td"})
    ids = []
    
    for row in case_rows:
        if row.find("a") != None:
            case_link = row.find("a")["href"]
            
            if "_id=" in case_link:
                case_id = re.search('_id=\d*&_uid=.+?&',case_link)[0].rstrip('&')
            # there can be no '_id', just '_uid'
            else:
                case_id = re.search('_uid=.+?&',case_link)[0].rstrip('&')
            ids.append(case_id)
            
    return ids

def _get_one_case_text_f2(soup) -> dict:
    '''
    Takes a soup of a page with case metadata
    Returns a dict with case metadata and decision text if present
    '''

    results = {}
    metadata = {}
    results["case_text"] = ""
    metadata["accused"] = []

    content = soup.find('div', {'id': 'search_results'})

    ### checking if the internal case ID is present 
    ### 
    id_text = soup.find('div', {'class': 'case-num'})
    if id_text != None:
        metadata["id_text"] = id_text.text.replace('\n',"").replace('\t',"")
    else:
        metadata["id_text"] = ""
    ###
    
    ### checking if there's any content
    ###
    if content != None:
        
        results["case_found"] = "True"

        # checking tabs
        tabs = soup.find("ul", id="case_bookmarks").find_all("li")
        
        for tab in tabs:
            ### case decision text
            if "Судебны" in tab.text:
                tab_id = tab.attrs['id'].replace('id','content')
                results["case_text"] = content.find('div',{'id':tab_id}).text.replace('"','\'').replace('\xa0','')

            ### accused info
            if "Лица" in tab.text:
                accused_list = []
                tab_id = tab.attrs['id'].replace('id','content')
                accused_content = content.find('div',{'id':tab_id})
                for tr in accused_content.find('table').find_all('tr')[1:]:
                    name = tr.find_all('td')[0].text
                    article = []
                    for td in tr.find_all('td'):
                        if 'УК РФ' in td.text:
                            article.extend(td.text.rstrip('УК РФ').split(';'))

                    accused_list.append({'name':name, 'article':article})

                metadata["accused"] = accused_list
        ###

        ### case metadata
        ###
        case_metadata = content.find('table', {'class':'law-case-table'})
        
        if case_metadata != None:
    
            for tr in case_metadata.find_all('tr'):
                # another case identifier
                if 'идентификатор' in tr.text:
                    metadata["uid_2"] = tr.find_all('td')[-1].text
                # receipt date
                if 'Дата поступления' in tr.text:
                    metadata["adm_date"] = tr.find_all('td')[-1].text
                # judge
                if 'Судья' in tr.text:
                    metadata["judge"] = tr.find_all('td')[-1].text
                # case status
                if 'Результат' in tr.text:
                    metadata["decision_result"] = tr.find_all('td')[-1].text
            ###   

        results["metadata"] = metadata
        
    else:
        results["case_found"] = "False"

    return results

def _get_captcha_f2(browser,website:str,autocaptcha="") -> str:
    '''
    Getting captcha code of form2 and displaying it; requires user's input;
    browser: selenium.webdriver.chrome.webdriver.WebDriver (the output of '_set_browser');
    website: str, website address;
    autocaptcha: str, API key from https://ocr.space/OCRAPI to guess captcha automatically, default ''; 
    Returns str, an addition to the link with captcha code;
    '''
    page_with_code = website + "/modules.php?name=sud_delo&name_op=sf&srv_num=1"

    tries = 0

    while tries <=3:

        browser.get(page_with_code)
        # checking if the search form is present
        check_content = _explicit_wait(browser,"ID","search-form",6)

        # form is present, getting captcha code
        if check_content == True:

            soup = BeautifulSoup(browser.page_source, 'html.parser')
            content = soup.find("form", {"class":"form-container"})
            # getting captcha ID
            captcha_id = content.find("input", {"name": "captchaid"})["value"]

            for img in content.find_all("img"):
                if "data" in img["src"]:
                    imgstring = img["src"].split(",")[1]

            imgdata = base64.b64decode(imgstring)

            # checking if API key is present for autorecognition of captcha
            if autocaptcha != "":
                captcha_guessed = _get_autocaptcha(autocaptcha,imgstring)

                # failed, enter captcha manually
                if captcha_guessed == "":

                    print("Autorecognition of captcha failed. Enter captcha manually")
                    # enlarging the captcha image
                    display(Image(imgdata, width=400, height=200))
                    # entering captcha manually
                    captcha_guessed = input("Enter captcha: ")

            # if no API key
            else:
                # enlarging the captcha image
                display(Image(imgdata, width=400, height=200))
                # entering captcha manually
                captcha_guessed = input("Enter captcha: ")

            captcha_addition = f"&captcha={captcha_guessed}&captchaid={captcha_id}"

            # success, stop trying
            break

        # failed to retrieve captcha
        else:
            tries += 1
            captcha_addition = ""
            # try again
            continue

    return captcha_addition


def _get_cases_texts_f2(website:str, region:str, court_code:str, start_date:str, end_date:str, path_to_driver:str, srv_num=['1'], path_to_save='', captcha=False, autocaptcha="") -> dict:
    '''
    Getting all court cases on one website in the indicated date range
    website: str, website address;
    region: str, region code; 
    court_code: str, required for form2 websites; to retrieve the codes, use 'https://raw.githubusercontent.com/dataout-org/sudrfparser/main/courts_info/sudrf_websites.json';
    Dates to indicate a date range in which to look for cases:
    (for example, the range 01.01.2021 and 31.12.2021 will get all the cases registered in a court in 2021)
        start_date: str, date of cases registration in a court, 'DD.MM.YYYY';
        end_date: str, date of cases registration in a court, 'DD.MM.YYYY';
    path_to_driver: str, path to Chrome driver;
    srv_num: list, servers where to look for cases, default ['1']; one website can have multiple servers with criminal cases of the first instance;
    path_to_save: str, path where to save the results, default '' (the same directory of the script execution);
    captcha: bool, if a website has captcha protection, default False; automatically checks if captcha is present, and if it's present: (1) a user will be asked to solve it or (2) if a user has API key from https://ocr.space/OCRAPI to guess captcha automatically, the captcha will be autorecognised;
    autocaptcha: str, API key from https://ocr.space/OCRAPI to guess captcha automatically, default ''; 
    Saves json files with all parsed cases per website's server (for example, if there are 2 servers on one website, there will be 2 json files); Logs errors and pages that were not parsed;
    Returns a dict with info about N cases found per server
    '''

    browser = _set_browser(path_to_driver)

    year = start_date.split('.')[-1]
    return_dict = {website:{"year":year,"n_cases_by_server":{}}}

    for server in srv_num:

        results_per_site = {}
        results_per_site[website] = {}
        num_cases = 0
        list_of_cases = []
        logs = {}

        # case__num_build coincides with server num
        module_form2 = f"/modules.php?name_op=r&name=sud_delo&srv_num={server}&_deloId=1540006&case__case_type=0&_new=0&case__vnkod={court_code}&case__num_build={server}&case__case_numberss=&case__judicial_uidss=&parts__namess=&case__entry_date1d={start_date}&case__entry_date2d={end_date}"

        link_to_site = website + module_form2

        # checking captcha
        if captcha == True:
            captcha_addition = _get_captcha_f2(browser,website,autocaptcha)
            link_to_site += captcha_addition

        # try to load the website content 3 times
        tries = 0

        while tries <= 3:
            try:
                browser.get(link_to_site)
                # explicitly waiting for the results table
                el_found = _explicit_wait(browser,"ID","resultTable",6)

                # if there is a table with results
                if el_found == True:

                    soup = BeautifulSoup(browser.page_source, 'html.parser')

                    stats = _num_cases_pages_f2(soup)
                    num_cases = stats[0]
                    num_pages = stats[1]

                    logs["cases_found"] = "True"
                    logs["driver_error"] = "False"
                    logs["pagination_error"] = []
                    results_per_site[website]["num_cases"] = num_cases

                    # getting cases on the first page
                    # this will be all the cases for 1 page results
                    # first, getting all the cases ids on the page
                    cases_ids_on_page = _get_cases_ids_per_page_f2(soup)

                    # iterating over cases and colecting texts
                    for case_id in cases_ids_on_page:

                        case_page = f"{website}/modules.php?name=sud_delo&name_op=case&{case_id}&_deloId=1540006&_caseType=0&_new=0&srv_num={server}"
                        browser.get(case_page)
                        # checking if tabs are loaded
                        el_found = _explicit_wait(browser,"ID","case_bookmarks",6)

                        if el_found == True:
                            soup_case = BeautifulSoup(browser.page_source, 'html.parser')
                            # getting case data
                            results_per_case = _get_one_case_text_f2(soup_case) 
                            results_per_case["case_id_uid"] = case_id
                            list_of_cases.append(results_per_case)

                        else:
                            results_per_case = {}
                            results_per_case["case_found"] = "False"
                            results_per_case["case_id_uid"] = case_id
                            list_of_cases.append(results_per_case)

                    if num_pages > 1:

                        for i in range(2,num_pages+1):
                            page_addition = f'&_page={i}'
                            link_with_page = link_to_site + page_addition

                            # adding Exception in case of the driver error
                            try:
                                browser.get(link_with_page)
                                el_found = _explicit_wait(browser,"ID","resultTable",6)
                                
                                # if there's no table content found
                                # check if it is because of captcha
                                if el_found == False and captcha == True and BeautifulSoup(browser.page_source, 'html.parser').find("div", {"id": "error"}):
                                    # getting new captcha
                                    captcha_addition = _get_captcha_f2(browser,website,autocaptcha)
                                    link_to_site = website + module_form2 + captcha_addition
                                    link_with_page = link_to_site + page_addition
                                    browser.get(link_with_page)
                                    # trying one more time
                                    el_found = _explicit_wait(browser,"ID","resultTable", 6)

                                if el_found == False:
                                    logs['pagination_error'].append(i)
                                
                                # if everything's ok
                                if el_found == True:
                                    soup = BeautifulSoup(browser.page_source, 'html.parser')
                                    cases_ids_on_page = _get_cases_ids_per_page_f2(soup)

                                    # iterating over cases and colecting texts
                                    for case_id in cases_ids_on_page:

                                        case_page = f"{website}/modules.php?name=sud_delo&name_op=case&{case_id}&_deloId=1540006&_caseType=0&_new=0&srv_num={server}"
                                        browser.get(case_page)

                                        # checking if tabs are loaded
                                        el_found = _explicit_wait(browser,"ID","case_bookmarks",6)
                                        if el_found == True:
                                            soup_case = BeautifulSoup(browser.page_source, 'html.parser')
                                            # getting case data
                                            results_per_case = _get_one_case_text_f2(soup_case)
                                            results_per_case["case_id_uid"] = case_id
                                            list_of_cases.append(results_per_case)
                                        else:
                                            results_per_case = {}
                                            results_per_case["case_found"] = "False"
                                            results_per_case["case_id_uid"] = case_id
                                            list_of_cases.append(results_per_case)

                            except WebDriverException:
                                # recording the N of page that couldn't be loaded
                                logs["driver_error"] = "True"
                                logs["pagination_error"].append(i)
                                # continue to the next page
                                continue

                    # saving data                
                    results_per_site[website]["cases"] = list_of_cases
                    results_per_site[website]["logs"] = logs

                    # results are saved, stop trying, break the while loop
                    break

                # no cases found (no results, error, or time out)
                else:
                    tries += 1

                    logs["cases_found"] = "False"
                    logs["driver_error"] = "False"
                    logs["pagination_error"] = []
                    results_per_site[website]["num_cases"] = num_cases
                    results_per_site[website]["cases"] = list_of_cases
                    results_per_site[website]["logs"] = logs

                    #try again
                    continue
                    

            except WebDriverException:
                tries += 1

                logs["cases_found"] = "False"
                logs["driver_error"] = "True"
                logs["pagination_error"] = []
                results_per_site[website]["num_cases"] = num_cases
                results_per_site[website]["cases"] = list_of_cases
                results_per_site[website]["logs"] = logs

                #try again
                continue

        file_name = f"{path_to_save}{region}_{website.replace('http://','').replace('.sudrf.ru','').replace('.','_').replace('/','')}_{server}_{year}.json"
        
        with open(file_name, 'w') as jf:
            json.dump(results_per_site, jf, ensure_ascii=False)

        return_dict[website]["n_cases_by_server"][server] = num_cases

    browser.close()

    return return_dict


### The main parser function ###

def get_cases(website:str, region:str, start_date:str, end_date:str, path_to_driver:str, court_code="", srv_num=['1'], path_to_save="", apikey=""):
    '''
    Getting texts of court decisions with metadata on one website for the indicated date range
    region: str, region code; use keys in 'https://github.com/dataout-org/sudrfparser/blob/main/courts_info/sudrf_websites.json'
    Dates to indicate a date range in which to look for cases:
    (for example, the range 01.01.2021 and 31.12.2021 will get all the cases registered in a court in 2021)
        start_date: str, date of cases registration in a court, 'DD.MM.YYYY';
        end_date: str, date of cases registration in a court, 'DD.MM.YYYY';
    path_to_driver: str, path to Chrome driver;
    court_code: str, required for form2 websites; to retrieve the codes, use 'https://raw.githubusercontent.com/dataout-org/sudrfparser/main/courts_info/sudrf_websites.json'; default '';
    srv_num: list, servers where to look for cases, default ['1']; one website can have multiple servers with criminal cases of the first instance;
    path_to_save: str, path where to save the results, default '' (the same directory of the script execution; note that there can be a lot of large json files);
    apikey: str, API key for autorecognition of captcha from https://ocr.space/OCRAPI; default ''; keep default if entering captcha manually;
    Saves json files with all parsed cases per website's server (for example, if there are 2 servers on one website, there will be 2 json files); Logs errors and pages that were not parsed;
    Returns a dict with info about N cases found per server (if parsed successfully); returns a status str if parsing is failed;
    '''

    # request the website soup
    # feed soup to check captcha and form

    browser = _set_browser(path_to_driver)
    link_to_site = website + "/modules.php?name=sud_delo&srv_num=1&name_op=sf&delo_id=1540005"

    # try to load the website content 3 times
    tries = 0
    content_found = False

    while tries <= 3:
        try:
            browser.get(link_to_site)
            content_found = _explicit_wait(browser,"ID","modSdpContent",6)
            # additional time if explicit wait fails
            time.sleep(3)

            if content_found == True:

                soup = BeautifulSoup(browser.page_source, 'html.parser')

                form_and_captcha = _check_form_and_captcha(soup)
                form_type = form_and_captcha["form_type"]
                captcha = form_and_captcha["captcha"]

                # parser for form1
                if form_type == "form1" and captcha == "False":
                    results = _get_cases_texts_f1(website, region, start_date, end_date, path_to_driver, srv_num, path_to_save)

                if form_type == "form1" and captcha == "True":
                    results = _get_cases_texts_f1(website, region, start_date, end_date, path_to_driver, srv_num, path_to_save, captcha=True, autocaptcha=apikey)

                # parser for form2
                if form_type == "form2" and captcha == "False":
                    results = _get_cases_texts_f2(website, region, court_code, start_date, end_date, path_to_driver, srv_num, path_to_save)

                if form_type == "form2" and captcha == "True":
                    results = _get_cases_texts_f2(website, region, court_code, start_date, end_date, path_to_driver, srv_num, path_to_save, captcha=True, autocaptcha=apikey)

                # no point in trying because websites with other forms are not parsed
                if form_type == "other":
                    results = f"{website} cannot be parsed"

                # succesful, stop trying
                break

            # no web driver error, but content was not loaded
            else:
                tries += 1
                continue

        # web driver error, try again
        except WebDriverException:
            tries += 1
            continue

    # give up if conent is still not loaded after 3 tries
    if content_found == False:
        results = f"Failed to load content of {website}"
    
    browser.close()
    
    return results


### Handling missed pages ###

def _get_missing_pages(dir_path:str,region_code:str,year:str) -> tuple:
    '''
    Getting files with missing pages;
    Returns a tuple: (N missed pages, files of websites with missing pages);
    Used as a subfunction for 'request_missing_pages'
    '''
    
    n_missed_pages = 0
    sites_with_pagination_errors = []
        
    region_year_files = [join(dir_path, f) for f in listdir(dir_path) 
                     if isfile(join(dir_path, f))
                     and f.endswith(".json")
                     and f.startswith(f"{region_code}_") and f"_{year}" in f]
    
    
    for path in region_year_files:
        with open(path,'r') as jf:
            cases_per_site = json.load(jf)
            for v in cases_per_site.values():
                if len(v['logs']["pagination_error"]) > 0:
                    sites_with_pagination_errors.append(path.split("/")[-1])
                    n_missed_pages += len(v['logs']["pagination_error"])
        
    return (n_missed_pages,sites_with_pagination_errors)


def request_missing_pages(dir_path:str,region_code:str,year:str,path_to_driver:str,apikey="") -> list:
    '''
    Handling missing pages by region and year: checking whether the result json files have missing pages and requesting cases on them;
    This function adds missing cases to the same resulting file (it overwrites files);
    dir_path: str, path to the directory with the json files of parsed cases;
    region_code: str, region code in the results json files, for which to check missing pages;
    year: str, year in the results json files, for which to check missing pages;
    (for example, the file '50_chehov_mo_1_2019.json' has the region code '50' and the year is '2019')
    path_to_driver: str, path to Chrome driver;
    apikey: str, API key for autorecognition of captcha from https://ocr.space/OCRAPI; default ''; keep default if entering captcha manually
    Returns a list with logs of N cases added per file
    '''

    logs_to_return = []
    missing_pages = _get_missing_pages(dir_path,region_code,year)

    for site in missing_pages[1]:
    
        # getting srv info from the file name
        srv = site.split("_")[-2]
        
        file_path = f"{dir_path}/{site}"
        
        with open(file_path,"r") as jf:
            site_data = json.load(jf)
            
        website = list(site_data.keys())[0]
            
        pages_to_reguest = site_data[website]["logs"]["pagination_error"]
        
        browser = _set_browser(path_to_driver)
        link_to_site = website + f"/modules.php?name=sud_delo&srv_num={srv}&name_op=sf&delo_id=1540005"
        
        all_cases_per_site_to_request = []
        not_parsed_pages = []
        new_cases_data = []
        
        try:
            browser.get(link_to_site)
            time.sleep(3)

            soup = BeautifulSoup(browser.page_source, 'html.parser')

            form_and_captcha = _check_form_and_captcha(soup)
            form_type = form_and_captcha["form_type"]
            captcha = form_and_captcha["captcha"]
            
            # form1
            if form_type == "form1":
                
                module = f'/modules.php?name=sud_delo&srv_num={srv}&name_op=r&delo_id=1540006&case_type=0&new=0&u1_case__ENTRY_DATE1D=01.01.{year}&u1_case__ENTRY_DATE2D=31.12.{year}&delo_table=u1_case&U1_PARTS__PARTS_TYPE='
                
                link_to_site = website + module

                # check captcha
                if captcha == "True":
                    captcha_addition = _get_captcha_f1(browser,website,apikey)
                    link_to_site += captcha_addition
                
                # collecting cases IDs per page
                for page in pages_to_reguest:
                    link_with_page = link_to_site + f"&page={page}"
                    
                    try:
                        browser.get(link_with_page)
                        soup = BeautifulSoup(browser.page_source, 'html.parser')
                        
                        if soup.find("table", {"id": "tablcont"}):
                            cases_ids_on_page = _get_cases_ids_per_page_f1(soup)
                            all_cases_per_site_to_request.extend(cases_ids_on_page)
                            
                    except WebDriverException:
                        not_parsed_pages.append(page)
                        continue
                        
                        
                # getting all cases data by their IDs
                for case_id in all_cases_per_site_to_request:
                    
                    case_page = f"{website}/modules.php?name=sud_delo&srv_num={srv}&name_op=case&{case_id}&delo_id=1540006"
                    browser.get(case_page)
                    soup_case = BeautifulSoup(browser.page_source, 'html.parser')

                    # getting case data
                    results_per_case = _get_one_case_text_f1(soup_case)
                    results_per_case["case_id_uid"] = case_id
                    new_cases_data.append(results_per_case)

            # form2
            if form_type == "form2":

                # getting court codes from a file
                court_codes_url = "https://github.com/dataout-org/sudrfparser/raw/main/courts_info/sudrf_websites.json"
                r = requests.get(court_codes_url)
                court_codes = r.json()

                for court in court_codes[region]:
                    if court["court_website"] == website:
                        court_code = court["court_id"]

                module_form2 = f'/modules.php?name_op=r&name=sud_delo&srv_num={srv}&_deloId=1540006&case__case_type=0&_new=0&case__vnkod={court_code}&case__num_build={srv}&case__case_numberss=&case__judicial_uidss=&parts__namess=&case__entry_date1d=01.01.{year}&case__entry_date2d=31.12.{year}'

                link_to_site = website + module_form2

                # checking captcha
                if captcha == "True":
                    captcha_addition = _get_captcha_f2(browser,website,apikey)
                    link_to_site += captcha_addition

                # collecting cases IDs per page
                for page in pages_to_reguest:
                    link_with_page = link_to_site + f'&_page={page}'
                    
                    try:
                        browser.get(link_with_page)
                        el_found = _explicit_wait(browser,"ID","resultTable", 6)
                        soup = BeautifulSoup(browser.page_source, 'html.parser')

                        # getting all the cases ids on the page
                        cases_ids_on_page = _get_cases_ids_per_page_f2(soup)
                        all_cases_per_site_to_request.extend(cases_ids_on_page)

                    except WebDriverException:
                        not_parsed_pages.append(page)
                        continue

                # getting all cases data by their IDs
                for case_id in all_cases_per_site_to_request:

                    case_page = f"{website}/modules.php?name=sud_delo&name_op=case&{case_id}&_deloId=1540006&_caseType=0&_new=0&srv_num={srv}"
                    browser.get(case_page)

                    # checking if tabs are loaded
                    el_found = _explicit_wait(browser,"ID","case_bookmarks",6)

                    soup_case = BeautifulSoup(browser.page_source, 'html.parser')
                    # getting case data
                    results_per_case = _get_one_case_text_f2(soup_case)
                    results_per_case["case_id_uid"] = case_id
                    new_cases_data.append(results_per_case)
                    
                
        except WebDriverException:
            not_parsed_pages = pages_to_reguest
            continue
            
        browser.close()
        
        if len(new_cases_data) > 0:
        
            site_data[website]["cases"].extend(new_cases_data)
            # if pages were not parsed again, keep them in the file
            site_data[website]["logs"]["pagination_error"] = not_parsed_pages

            # export new file / overwrite
            with open(file_path, 'w') as jf:
                json.dump(site_data,jf,ensure_ascii=False)

            status = f"{len(new_cases_data)} cases were added to {site}"
            
        else:
            status = f"No cases were added to {site}"

        logs_to_return.append(status)

    return logs_to_return


### Compressing results files by region and year ###

def compress_by_region_year(dir_path:str,region_code:str,year:str,path_to_save:str) -> str:
    '''
    Compressing json files with cases texts: putting all cases of one region per year in one compressed json file (gzip);
    If there are multiple files for one website (results from several servers), merges them into one file;
    dir_path: str, path to the directory with the json files of parsed cases;
    region_code: str, a region to compress; for example '78';
    year: str, a year to merge files by;
    path_to_save: str, path to the directory, where to save the compressed gzip file (!NB the file can be large);
    Returns str: status of the compression
    '''
    
    compressed_filename = f"{region_code}_{year}_gzip.json"
        
    # all file paths by region and year
    region_year_files = [join(dir_path, f) for f in listdir(dir_path) 
                     if isfile(join(dir_path, f))
                     and f.endswith(".json")
                     and f.startswith(f"{region_code}_") and f"_{year}" in f]
    

    # merging multiple json files into one
    merged = {}
    
    # check if the directory contains several files of different srv
    list_of_court_str_ids = []

    for file_path in region_year_files:

        court_str_id = file_path.split('/')[-1].split('.')[0].replace(f"{region_code}_",'').replace(f"_{year}",'')
        srv_num_str = re.search('(_\d)',court_str_id)[0]
        court_str_id = court_str_id.replace(srv_num_str,'')
        list_of_court_str_ids.append(court_str_id)

    court_cases_by_srv = dict(Counter(list_of_court_str_ids))

    # if there are several srv files, merge them in one and add to the common merged file
    for court_name, n_srv in court_cases_by_srv.items():

        if n_srv > 1:

            combined_by_srv = {}
            combined_by_srv_website = {}

            for file_path in region_year_files:
                if court_name in file_path:

                    with open(file_path, 'r') as jf:
                        cases_by_srv = json.load(jf)
                        website = list(cases_by_srv.keys())[0]
                        # srv num in the file name can be 2 digits
                        srv_num_str = "srv_" + re.search('(_\d*_)',file_path)[0].replace('_','')
                        combined_by_srv[srv_num_str]= cases_by_srv[website]
                        combined_by_srv_website[website] = {}

            combined_by_srv_website[website] = combined_by_srv
            merged.update(combined_by_srv_website)
            
        # if there is one srv, add cases to the merged files directly
        else:
            for file_path in region_year_files:
                if court_name in file_path:

                    with open(file_path, 'r') as jf:
                        cases_by_court = json.load(jf)
                        merged.update(cases_by_court)
                        
    # compress the merged json file
    with gzip.open(f"{path_to_save}/{compressed_filename}", 'w') as gzip_out:
        gzip_out.write(json.dumps(merged).encode('utf-8'))

    return f"Results for the region {region_code} and year {year} are compressed and saved in {path_to_save}"