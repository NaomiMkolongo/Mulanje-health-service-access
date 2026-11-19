-- TEMPORARY sample data. Names are plausible, coordinates are APPROXIMATE
-- placeholders inside Mulanje District. Replace with surveyed data.
DELETE FROM mulanje_health.facility WHERE is_sample;

INSERT INTO mulanje_health.facility
 (name, facility_type, ownership, traditional_authority, beds, staff_count, catchment_population,
  services, has_ambulance, has_electricity, is_sample, notes, geom)
SELECT v.name, v.ftype, v.own, v.ta, v.beds, v.staff, v.pop, v.services, v.amb, v.elec, true,
       'TEMPORARY sample record',
       ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)
FROM (VALUES
 ('Mulanje District Hospital','Hospital','Government','Mabuka',180,95,85000,'OPD, Maternity, Surgery, Paediatrics, Laboratory, HIV/ART, Pharmacy',true,true,35.5005,-16.0290),
 ('Mulanje Mission Hospital','Hospital','CHAM','Juma',150,80,70000,'OPD, Maternity, Surgery, Laboratory, HIV/ART, Eye clinic',true,true,35.5560,-15.9920),
 ('Chitakale Health Centre','Health Centre','Government','Mabuka',30,22,42000,'OPD, Maternity, Immunisation, HIV/ART, Laboratory',true,true,35.5800,-15.9600),
 ('Thuchila Health Centre','Health Centre','Government','Nkanda',24,18,36000,'OPD, Maternity, Immunisation, Malaria',false,true,35.4300,-16.0900),
 ('Muloza Health Centre','Health Centre','Government','Mabuka',20,15,33000,'OPD, Maternity, Immunisation, Malaria',false,false,35.7000,-16.0300),
 ('Chonde Health Centre','Health Centre','Government','Chikumbu',22,16,30000,'OPD, Maternity, Immunisation, HIV/ART',false,true,35.3900,-15.9500),
 ('Mpala Health Centre','Health Centre','Government','Nkanda',18,14,27000,'OPD, Maternity, Immunisation',false,false,35.6200,-16.1200),
 ('Nkhulambe Health Centre','Health Centre','CHAM','Njema',16,12,25000,'OPD, Maternity, Immunisation, Nutrition',false,true,35.4600,-16.1300),
 ('Likhubula Health Centre','Health Centre','Government','Mabuka',14,11,21000,'OPD, Immunisation, Malaria, Family planning',false,false,35.6050,-15.9950),
 ('Nambazo Health Centre','Health Centre','Government','Juma',15,12,22000,'OPD, Maternity, Immunisation',false,false,35.5300,-16.1000),
 ('Linje Dispensary','Dispensary','Government','Chikumbu',4,5,12000,'OPD, Immunisation, Family planning',false,false,35.4700,-15.9900),
 ('Fort Lister Dispensary','Dispensary','Government','Njema',4,4,10000,'OPD, Immunisation',false,false,35.5800,-16.0500),
 ('Namphungo Health Post','Health Post','Government','Nkanda',0,2,5000,'First aid, Immunisation outreach, Health education',false,false,35.5100,-16.0800),
 ('Chambe Health Post','Health Post','NGO','Mabuka',0,3,4000,'First aid, Malaria testing, Health education',false,false,35.6000,-15.9300),
 ('Mulanje Urban Clinic','Clinic','Private','Mabuka',6,8,15000,'OPD, Laboratory, Pharmacy',false,true,35.4980,-16.0340)
) AS v(name, ftype, own, ta, beds, staff, pop, services, amb, elec, lon, lat);
